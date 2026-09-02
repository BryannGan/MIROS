"""
`miros setup`: the 3D model and the boundary-condition form on one page.

Left: the surface with every cap coloured and labelled; click a cap to select
it. Right: one row per cap (name, area, inlet, flow share), the pressure
anchor and targets. Save writes model.inlet, model.cap_names,
boundary_conditions.flow_split and boundary_conditions.pressure_mmHg into
case.yaml, keeping the file's comments.

Needs the optional GUI stack: pip install pyvistaqt PySide6
"""
import re
import sys
from pathlib import Path
from typing import List, Optional

import numpy as np

_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')


def _require_qt():
    try:
        import pyvistaqt  # noqa: F401
        import qtpy  # noqa: F401
    except ImportError:
        raise RuntimeError("the setup window needs the GUI extra: pip install pyvistaqt PySide6")


def _load(case_dir: Path):
    from ..case import Case
    from ..geometry import caps as C
    case = Case(case_dir)
    m = case.config.model
    src = case.surface_work if case.surface_work.exists() else case.resolve(m.surface)
    surf = C.read_polydata(src)
    caps = C.make_caps(surf, inlet=m.inlet, names=m.cap_names)
    return case, surf, caps


class SetupWindow:
    """Built lazily so importing this module never needs Qt."""

    def __init__(self, case_dir, offscreen: bool = False):
        _require_qt()
        from qtpy import QtCore, QtWidgets
        from pyvistaqt import QtInteractor
        import pyvista as pv
        self.Qt = QtCore
        self.W = QtWidgets

        self.case, self.surf, self.caps = _load(Path(case_dir))
        self.caps.sort(key=lambda c: -c.area)                     # decreasing area = cap_names order
        bc = self.case.config.boundary_conditions
        units = self.case.config.model.units

        self.win = QtWidgets.QMainWindow()
        self.win.setWindowTitle('MIROS setup: %s' % self.case.config.name)
        split = QtWidgets.QSplitter()
        self.win.setCentralWidget(split)

        # ---- 3D view --------------------------------------------------
        self.actors = {}
        self.plotter = None
        if not offscreen:
            self.plotter = QtInteractor(split)
            split.addWidget(self.plotter.interactor)
            self.plotter.add_mesh(pv.wrap(self.surf), color='lightgray', opacity=0.35, name='wall')
            for c in self.caps:
                self.actors[c.name] = self.plotter.add_mesh(pv.wrap(c.polydata), color=self._color(c), name='cap:' + c.name)
            self._labels()
            self.plotter.enable_mesh_picking(callback=self._picked, show=False, show_message=False, left_clicking=True)
            self.plotter.add_text('click a cap to select it', position='lower_left', font_size=10)
            self.plotter.reset_camera()

        # ---- form -----------------------------------------------------
        panel = QtWidgets.QWidget()
        split.addWidget(panel)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        form = QtWidgets.QVBoxLayout(panel)

        form.addWidget(QtWidgets.QLabel('<b>Caps</b> — name them, pick the inlet, give each outlet its share of the flow'))
        self.table = QtWidgets.QTableWidget(len(self.caps), 4)
        self.table.setHorizontalHeaderLabels(['name', 'area [%s²]' % units, 'inlet', 'flow %'])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.inlet_group = QtWidgets.QButtonGroup(panel)
        self.name_edits: List = []
        self.split_boxes: List = []
        self.inlet_buttons: List = []
        for r, c in enumerate(self.caps):
            name = QtWidgets.QLineEdit(c.name)
            name.textEdited.connect(self._names_changed)
            self.name_edits.append(name)
            self.table.setCellWidget(r, 0, name)
            area = QtWidgets.QTableWidgetItem('%.4f' % c.area)
            area.setFlags(QtCore.Qt.ItemIsEnabled)
            self.table.setItem(r, 1, area)
            radio = QtWidgets.QRadioButton()
            radio.setChecked(c.is_inlet)
            radio.toggled.connect(self._inlet_changed)
            self.inlet_group.addButton(radio, r)
            self.inlet_buttons.append(radio)
            holder = QtWidgets.QWidget(); lay = QtWidgets.QHBoxLayout(holder); lay.setContentsMargins(0, 0, 0, 0)
            lay.addStretch(); lay.addWidget(radio); lay.addStretch()
            self.table.setCellWidget(r, 2, holder)
            box = QtWidgets.QDoubleSpinBox()
            box.setRange(0.0, 100.0); box.setDecimals(1); box.setSingleStep(1.0); box.setSuffix(' %')
            box.setValue(float(bc.flow_split.get(c.name, 0.0)))
            box.valueChanged.connect(self._splits_changed)
            self.split_boxes.append(box)
            self.table.setCellWidget(r, 3, box)
        self.table.currentCellChanged.connect(lambda r, *_: self._select(r))
        form.addWidget(self.table)

        row = QtWidgets.QHBoxLayout()
        self.total = QtWidgets.QLabel()
        row.addWidget(self.total)
        row.addStretch()
        equal = QtWidgets.QPushButton('Equal split')
        equal.clicked.connect(self._equal_split)
        row.addWidget(equal)
        by_area = QtWidgets.QPushButton('Split by area')
        by_area.setToolTip("share proportional to each outlet's cap area")
        by_area.clicked.connect(self._area_split)
        row.addWidget(by_area)
        form.addLayout(row)

        form.addWidget(QtWidgets.QLabel('<b>Pressure target</b>'))
        grid = QtWidgets.QFormLayout()
        self.anchor = QtWidgets.QComboBox()
        grid.addRow('measured at', self.anchor)
        p = bc.pressure_mmHg
        self.sys = QtWidgets.QDoubleSpinBox(); self.sys.setRange(1, 400); self.sys.setSuffix(' mmHg'); self.sys.setValue(p.systolic)
        self.dia = QtWidgets.QDoubleSpinBox(); self.dia.setRange(1, 400); self.dia.setSuffix(' mmHg'); self.dia.setValue(p.diastolic)
        grid.addRow('systolic', self.sys)
        grid.addRow('diastolic', self.dia)
        mean_row = QtWidgets.QHBoxLayout()
        self.mean_on = QtWidgets.QCheckBox('also target the mean')
        self.mean = QtWidgets.QDoubleSpinBox(); self.mean.setRange(1, 400); self.mean.setSuffix(' mmHg')
        self.mean.setValue(p.mean if p.mean is not None else (p.diastolic + (p.systolic - p.diastolic) / 3.0))
        self.mean_on.setChecked(p.mean is not None)
        self.mean.setEnabled(p.mean is not None)
        self.mean_on.toggled.connect(self.mean.setEnabled)
        mean_row.addWidget(self.mean_on); mean_row.addWidget(self.mean)
        grid.addRow('mean', mean_row)
        form.addLayout(grid)
        hint = QtWidgets.QLabel("The pulse pressure at the inlet has a floor set by the inflow waveform and the vessel "
                                "inertia; if a target is out of reach the tuner says so and keeps its best result.")
        hint.setWordWrap(True); hint.setStyleSheet('color: gray')
        form.addWidget(hint)

        form.addStretch()
        self.message = QtWidgets.QLabel(); self.message.setWordWrap(True)
        form.addWidget(self.message)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self.save_btn = QtWidgets.QPushButton('Save to case.yaml')
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self.save)
        cancel = QtWidgets.QPushButton('Close without saving')
        cancel.clicked.connect(self.win.close)
        buttons.addWidget(cancel); buttons.addWidget(self.save_btn)
        form.addLayout(buttons)

        self._anchor_items(p.at)
        self._inlet_changed()
        self.win.resize(1300, 720)

    # ---- helpers ------------------------------------------------------
    @staticmethod
    def _color(cap, selected=False):
        if selected:
            return 'gold'
        return 'crimson' if cap.is_inlet else 'steelblue'

    def _names(self) -> List[str]:
        return [e.text().strip() for e in self.name_edits]

    def _inlet_row(self) -> int:
        return max(self.inlet_group.checkedId(), 0)

    def _outlet_rows(self) -> List[int]:
        return [r for r in range(len(self.caps)) if r != self._inlet_row()]

    def _labels(self):
        if self.plotter is None:
            return
        names = self._names()
        pts = [c.centroid + 1.5 * c.radius * c.normal for c in self.caps]
        txt = ['%s%s\n%.3f' % (names[i], ' (inlet)' if i == self._inlet_row() else '', c.area) for i, c in enumerate(self.caps)]
        self.plotter.add_point_labels(np.array(pts), txt, name='labels', font_size=12, point_size=0,
                                      shape_opacity=0.65, always_visible=True)

    def _anchor_items(self, current: str):
        names = self._names()
        items = ['inlet'] + [names[r] for r in self._outlet_rows()]
        self.anchor.blockSignals(True)
        self.anchor.clear()
        self.anchor.addItems(items)
        self.anchor.setCurrentIndex(items.index(current) if current in items else 0)
        self.anchor.blockSignals(False)

    # ---- reactions ----------------------------------------------------
    def _select(self, row: int):
        if self.plotter is None or row < 0:
            return
        for i, c in enumerate(self.caps):
            self.actors[c.name].prop.color = self._color(c, selected=(i == row))
        self.plotter.render()

    def _picked(self, mesh):
        c0 = np.asarray(mesh.center)
        row = int(np.argmin([np.linalg.norm(c.centroid - c0) for c in self.caps]))
        self.table.setCurrentCell(row, 0)
        self._select(row)

    def _inlet_changed(self, *_):
        inlet = self._inlet_row()
        for r, c in enumerate(self.caps):
            c.is_inlet = (r == inlet)
            self.split_boxes[r].setEnabled(r != inlet)
            if self.plotter is not None:
                self.actors[c.name].prop.color = self._color(c)
        self._anchor_items(self.anchor.currentText())
        self._labels()
        self._splits_changed()
        if self.plotter is not None:
            self.plotter.render()

    def _names_changed(self, *_):
        self._anchor_items(self.anchor.currentText())
        self._labels()
        if self.plotter is not None:
            self.plotter.render()

    def _splits_changed(self, *_):
        tot = sum(self.split_boxes[r].value() for r in self._outlet_rows())
        ok = abs(tot - 100.0) < 0.05
        self.total.setText('outlets total: <b>%.1f %%</b>%s' % (tot, '' if ok else '  (must be 100)'))
        self.total.setStyleSheet('' if ok else 'color: #b3261e')

    def _equal_split(self):
        rows = self._outlet_rows()
        for r in rows:
            self.split_boxes[r].setValue(round(100.0 / len(rows), 1))
        self._fix_rounding(rows)

    def _area_split(self):
        rows = self._outlet_rows()
        tot = sum(self.caps[r].area for r in rows)
        for r in rows:
            self.split_boxes[r].setValue(round(100.0 * self.caps[r].area / tot, 1))
        self._fix_rounding(rows)

    def _fix_rounding(self, rows):
        diff = 100.0 - sum(self.split_boxes[r].value() for r in rows)
        if rows and abs(diff) > 1e-6:
            big = max(rows, key=lambda r: self.split_boxes[r].value())
            self.split_boxes[big].setValue(round(self.split_boxes[big].value() + diff, 1))

    # ---- validation / save --------------------------------------------
    def values(self):
        names = self._names()
        for n in names:
            if not _NAME_RE.match(n):
                raise ValueError("cap name %r: use letters, digits and underscores, starting with a letter" % n)
        if len(set(names)) != len(names):
            raise ValueError("cap names must be unique")
        inlet = names[self._inlet_row()]
        split = {names[r]: self.split_boxes[r].value() for r in self._outlet_rows()}
        if abs(sum(split.values()) - 100.0) > 0.05:
            raise ValueError("the outlet flow shares sum to %.1f %%, they must sum to 100" % sum(split.values()))
        if any(v <= 0 for v in split.values()):
            raise ValueError("every outlet needs a positive flow share")
        if self.sys.value() <= self.dia.value():
            raise ValueError("systolic must exceed diastolic")
        mean = self.mean.value() if self.mean_on.isChecked() else None
        if mean is not None and not (self.dia.value() < mean < self.sys.value()):
            raise ValueError("the mean must lie between diastolic and systolic")
        at = self.anchor.currentText()
        return dict(inlet=inlet, cap_names=names, flow_split=split,
                    pressure=dict(at=at, systolic=self.sys.value(), diastolic=self.dia.value(), mean=mean))

    def save(self):
        from ..config_edit import update_case_yaml
        try:
            v = self.values()
        except ValueError as e:
            self.message.setText('<span style="color:#b3261e">%s</span>' % e)
            return
        update_case_yaml(self.case.yaml, **v)
        self.message.setText('saved %s — now: miros run %s' % (self.case.yaml, self.case.dir))
        self.win.statusBar().showMessage('saved', 5000)

    def show(self):
        self.win.show()


def run_setup(case_dir) -> int:
    _require_qt()
    from qtpy import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    w = SetupWindow(case_dir)
    w.show()
    return app.exec_() if hasattr(app, 'exec_') else app.exec()
