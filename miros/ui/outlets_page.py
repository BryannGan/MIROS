"""
The Outlets step of `miros gui`: review the cuts that open the vessel ends
before anything is clipped.

The segment stage finds every vessel end and marks the ones it would cut.
This page shows all of them on the surface: a solid disc for a cut that is
on, a faint one for a candidate that is off. Nothing is clipped until
"Apply cuts", which writes the chosen planes to case.yaml and runs the
preprocess stage.
"""
import json
from pathlib import Path
from typing import List, Optional

import numpy as np


class OutletsPage:
    """Built by MainWindow; `widget` is the Qt page."""

    def __init__(self, main):
        from qtpy import QtWidgets
        self.main = main
        self.W = QtWidgets
        self.planes: List[dict] = []
        self.surf = None
        self.selected: Optional[int] = None

        page = QtWidgets.QWidget()
        self.widget = page
        lay = QtWidgets.QVBoxLayout(page)
        self.info = QtWidgets.QLabel('<b>Open the vessel ends</b> — every end found on the surface is listed, '
                                     'the proposed cuts ticked. Tick or untick a cut, say which one is the inlet, '
                                     'move a cut along its vessel if it sits badly, then apply. Nothing is '
                                     'clipped before that. A cut that would split the model rather than open an '
                                     'end is reported and left out, so try moving it toward the vessel end.')
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['cut', 'name', 'radius', 'inlet', 'where it is', 'why it is off'])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.currentCellChanged.connect(lambda r, *_: self.select(r))
        lay.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel('selected cut:'))
        self.move_in = QtWidgets.QPushButton('◀ further in')
        self.move_in.setToolTip('Move the cut deeper into the vessel, a quarter radius at a time')
        self.move_in.clicked.connect(lambda: self.nudge(-0.25))
        self.move_out = QtWidgets.QPushButton('further out ▶')
        self.move_out.setToolTip('Move the cut toward the vessel end')
        self.move_out.clicked.connect(lambda: self.nudge(0.25))
        self.flip = QtWidgets.QPushButton('flip side')
        self.flip.setToolTip('Cut away the other side: use this when a cut removed the wrong piece')
        self.flip.clicked.connect(self.flip_normal)
        self.radius = QtWidgets.QDoubleSpinBox(); self.radius.setRange(0.01, 100); self.radius.setDecimals(3)
        self.radius.setSingleStep(0.05)
        self.radius.valueChanged.connect(self.set_radius)
        for w in (self.move_in, self.move_out, self.flip, QtWidgets.QLabel('radius [cm]'), self.radius):
            row.addWidget(w)
        row.addStretch()
        lay.addLayout(row)

        row2 = QtWidgets.QHBoxLayout()
        self.count = QtWidgets.QLabel('')
        row2.addWidget(self.count)
        row2.addStretch()
        self.reload_btn = QtWidgets.QPushButton('Reload proposals')
        self.reload_btn.setToolTip('Throw away the edits and take the segment stage\'s proposal again')
        self.reload_btn.clicked.connect(self.reload)
        self.save_btn = QtWidgets.QPushButton('Save cuts')
        self.save_btn.clicked.connect(self.save)
        self.apply_btn = QtWidgets.QPushButton('▶ Apply cuts and find the caps')
        self.apply_btn.clicked.connect(self.apply)
        for w in (self.reload_btn, self.save_btn, self.apply_btn):
            row2.addWidget(w)
        lay.addLayout(row2)
        self.message = QtWidgets.QLabel(''); self.message.setWordWrap(True)
        lay.addWidget(self.message)

    # ---- loading ---------------------------------------------------------
    def load_from_case(self) -> bool:
        """Planes from case.yaml if they were saved, else the segment stage's proposal."""
        case = self.main.case
        if case is None:
            return False
        from ..stages.preprocess import source_surface
        planes = [dict(p) for p in case.config.model.outlets]
        if not planes:
            f = case.work / 'outlets_proposed.json'
            if not f.exists():
                self.planes, self.surf = [], None
                self.refresh()
                return False
            planes = json.loads(f.read_text())
        self.planes = [dict(p) for p in planes]
        src = source_surface(case)
        if src.exists():
            from ..geometry import caps as C
            self.surf = C.read_polydata(src)
        self.selected = 0 if self.planes else None
        self.refresh()
        self.show_scene()
        return True

    def reload(self):
        case = self.main.case
        f = case.work / 'outlets_proposed.json' if case else None
        if not f or not f.exists():
            return self.main.error('no proposal on disk: run the Segment step first')
        self.planes = [dict(p) for p in json.loads(f.read_text())]
        self.selected = 0 if self.planes else None
        self.refresh()
        self.show_scene()
        self.message.setText('back to the %d ends the segment stage proposed' % len(self.planes))

    # ---- table and scene -------------------------------------------------
    def refresh(self):
        W = self.W
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.planes))
        for r, p in enumerate(self.planes):
            box = W.QTableWidgetItem()
            box.setFlags(self.main.QtCore.Qt.ItemIsUserCheckable | self.main.QtCore.Qt.ItemIsEnabled)
            box.setCheckState(self.main.QtCore.Qt.Checked if p.get('use', True) else self.main.QtCore.Qt.Unchecked)
            self.table.setItem(r, 0, box)
            self.table.setItem(r, 1, W.QTableWidgetItem(p.get('name', '')))
            self.table.setItem(r, 2, W.QTableWidgetItem('%.3f' % p.get('radius', 0.0)))
            inlet = W.QTableWidgetItem()
            inlet.setFlags(self.main.QtCore.Qt.ItemIsUserCheckable | self.main.QtCore.Qt.ItemIsEnabled)
            inlet.setCheckState(self.main.QtCore.Qt.Checked if p.get('inlet') else self.main.QtCore.Qt.Unchecked)
            self.table.setItem(r, 3, inlet)
            self.table.setItem(r, 4, W.QTableWidgetItem(', '.join('%.1f' % v for v in p.get('origin', []))))
            self.table.setItem(r, 5, W.QTableWidgetItem('' if p.get('use', True) else p.get('skipped', '')))
        self.table.blockSignals(False)
        try:
            self.table.itemChanged.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.table.itemChanged.connect(self._item_changed)
        on = sum(1 for p in self.planes if p.get('use', True))
        self.count.setText('<b>%d of %d ends will be cut</b> (%d caps: 1 inlet, %d outlets)'
                           % (on, len(self.planes), on, max(on - 1, 0)))
        if self.selected is not None and 0 <= self.selected < len(self.planes):
            self.radius.blockSignals(True)
            self.radius.setValue(float(self.planes[self.selected].get('radius', 0.1)))
            self.radius.blockSignals(False)

    def _item_changed(self, item):
        r, c = item.row(), item.column()
        if not (0 <= r < len(self.planes)):
            return
        if c == 0:
            self.planes[r]['use'] = item.checkState() == self.main.QtCore.Qt.Checked
            if self.planes[r]['use']:
                self.planes[r].pop('skipped', None)
            self.refresh()
            self.show_scene()
        elif c == 1:
            self.planes[r]['name'] = item.text().strip() or self.planes[r]['name']
            self.show_scene()
        elif c == 3 and item.checkState() == self.main.QtCore.Qt.Checked:
            for i, q in enumerate(self.planes):        # exactly one inlet
                q['inlet'] = (i == r)
            self.planes[r]['use'] = True
            self.planes[r].pop('skipped', None)
            n = 0
            for q in self.planes:
                if q['inlet']:
                    q['name'] = 'inlet'
                else:
                    n += 1
                    q['name'] = q['name'] if q['name'] not in ('inlet', '') else 'cap_%d' % n
            self.refresh()
            self.show_scene()
            self.message.setText('%s is the inlet now' % self.planes[r]['name'])

    def select(self, row):
        if row is None or not (0 <= row < len(self.planes)):
            return
        self.selected = row
        self.radius.blockSignals(True)
        self.radius.setValue(float(self.planes[row].get('radius', 0.1)))
        self.radius.blockSignals(False)
        self.show_scene()

    def show_scene(self):
        if self.surf is None:
            return
        self.main.viewer.show_planes(self.surf, self.planes, self.selected, pick_callback=self._picked)

    def _picked(self, point):
        """Clicking near a cut selects it; the table follows."""
        if not self.planes:
            return
        p = np.asarray(point, float)
        r = int(np.argmin([np.linalg.norm(np.asarray(q['origin'], float) - p) for q in self.planes]))
        self.table.setCurrentCell(r, 0)
        self.select(r)

    # ---- editing ---------------------------------------------------------
    def _current(self):
        if self.selected is None or not (0 <= self.selected < len(self.planes)):
            self.main.error('select a cut in the table first')
            return None
        return self.planes[self.selected]

    def nudge(self, radii: float):
        p = self._current()
        if p is None:
            return
        o = np.asarray(p['origin'], float) + radii * float(p['radius']) * np.asarray(p['normal'], float)
        p['origin'] = [float(v) for v in o]
        self.refresh()
        self.show_scene()
        self.message.setText('moved %s %s by %.2f cm' % (p['name'], 'out' if radii > 0 else 'in',
                                                         abs(radii) * float(p['radius'])))

    def flip_normal(self):
        p = self._current()
        if p is None:
            return
        p['normal'] = [-float(v) for v in p['normal']]
        self.show_scene()
        self.message.setText('%s now cuts away the other side' % p['name'])

    def set_radius(self, value):
        p = self._current()
        if p is None:
            return
        p['radius'] = float(value)
        self.show_scene()

    # ---- saving and applying ---------------------------------------------
    def save(self):
        from ..config_edit import set_outlets
        if self.main.case is None:
            return self.main.error('open a case first')
        if not self.planes:
            return self.main.error('no cuts to save')
        if not any(p.get('use', True) for p in self.planes):
            return self.main.error('tick at least the inlet')
        set_outlets(self.main.case.yaml, self.planes)
        self.main.refresh_status()
        self.message.setText('saved %d cuts to %s' % (sum(1 for p in self.planes if p.get('use', True)),
                                                      self.main.case.yaml))
        self.main.status('cuts saved')

    def apply(self):
        if self.main.case is None:
            return self.main.error('open a case first')
        if not self.planes:
            return self.main.error('run the Segment step first')
        self.save()
        # only the clipping: re-running the segment stage here would trace the image again
        self.main.start_run(None, True, until='preprocess', only=['preprocess'], on_done=self._done)

    def _done(self, ok):
        if not ok:
            self.main.tabs.setCurrentIndex(self.main.TAB_OUTLETS)
            self.message.setText('the cuts did not work out — see the log on the Run step, then move or untick '
                                 'the cut it names and apply again')
            return
        self.main.load_case(self.main.case.dir)
        self.main.tabs.setCurrentIndex(self.main.TAB_MODEL)
        self.main.status('caps found — continue with the inflow')
