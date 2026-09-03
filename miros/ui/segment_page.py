"""
The Segment step of `miros gui`: a CT/MR volume shown as three slices in
the 3D view, seeds placed by clicking on the slices, the pretrained model
chosen (and downloaded) here, and SeqSeg run in the background.

Seeds are what SeqSeg needs: a start point, a second point a little
further along the vessel (the direction), and the lumen radius there.
Two clicks place a seed; the radius comes from the spin box.
"""
import threading
from pathlib import Path
from typing import List, Optional

import numpy as np


class SegmentPage:
    """Built by MainWindow; `widget` is the Qt page. Needs qtpy (checked by the window)."""

    def __init__(self, main):
        from qtpy import QtCore, QtWidgets
        self.main = main
        self.W = QtWidgets
        self.QtCore = QtCore
        self.image = None                 # pyvista ImageData in world coordinates
        self.image_path: Optional[Path] = None
        self.seeds: List[dict] = []
        self.pending = None               # first click of a seed, waiting for the direction click
        self._download_thread = None

        page = QtWidgets.QWidget()
        self.widget = page
        lay = QtWidgets.QVBoxLayout(page)
        lay.addWidget(QtWidgets.QLabel('<b>Start from an image</b> — SeqSeg traces the vessel tree from seeds; '
                                       'MIROS opens the outlets and continues from there.'))
        form = QtWidgets.QFormLayout()
        self.image_edit = QtWidgets.QLineEdit()
        b = QtWidgets.QPushButton('Browse…'); b.clicked.connect(self._browse_image)
        r = QtWidgets.QHBoxLayout(); r.addWidget(self.image_edit); r.addWidget(b)
        form.addRow('image (.nii.gz / .mha / .nrrd)', r)
        self.units = QtWidgets.QComboBox(); self.units.addItems(['mm', 'cm'])
        self.units_hint = QtWidgets.QLabel(''); self.units_hint.setStyleSheet('color: gray')
        r2 = QtWidgets.QHBoxLayout(); r2.addWidget(self.units); r2.addWidget(self.units_hint); r2.addStretch()
        form.addRow('image units', r2)
        self.model = QtWidgets.QComboBox()
        from ..models import MODELS
        for k, m in MODELS.items():
            self.model.addItem('%s — %s' % (k, m['description']), k)
        self.model_status = QtWidgets.QLabel('')
        self.download_btn = QtWidgets.QPushButton('Download'); self.download_btn.clicked.connect(self._download)
        r3 = QtWidgets.QHBoxLayout(); r3.addWidget(self.model, 1); r3.addWidget(self.model_status); r3.addWidget(self.download_btn)
        form.addRow('model', r3)
        self.model.currentIndexChanged.connect(lambda *_: self._model_status())
        self.case_edit = QtWidgets.QLineEdit()
        b2 = QtWidgets.QPushButton('Browse…'); b2.clicked.connect(self._browse_case_dir)
        r4 = QtWidgets.QHBoxLayout(); r4.addWidget(self.case_edit); r4.addWidget(b2)
        form.addRow('case folder', r4)
        lay.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        self.create_btn = QtWidgets.QPushButton('Create case from this image'); self.create_btn.clicked.connect(self.create_case)
        row.addWidget(self.create_btn); row.addStretch()
        lay.addLayout(row)

        lay.addWidget(QtWidgets.QLabel('<b>Seeds</b> — click a slice for the start point, click again a little further '
                                       'along the vessel for the direction. Use the sliders in the 3D view to move the slices.'))
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(QtWidgets.QLabel('radius at the seed'))
        self.radius = QtWidgets.QDoubleSpinBox(); self.radius.setRange(0.01, 100); self.radius.setDecimals(2); self.radius.setValue(1.0)
        srow.addWidget(self.radius)
        self.radius_unit = QtWidgets.QLabel('[cm]'); srow.addWidget(self.radius_unit)
        srow.addStretch()
        self.pick_btn = QtWidgets.QPushButton('Add seed by clicking'); self.pick_btn.setCheckable(True)
        self.pick_btn.toggled.connect(self._toggle_pick)
        self.pick_btn.setEnabled(False)
        srow.addWidget(self.pick_btn)
        lay.addLayout(srow)
        self.units.currentTextChanged.connect(lambda u: self.radius_unit.setText('[%s]' % u))
        self.seed_table = QtWidgets.QTableWidget(0, 4)
        self.seed_table.setHorizontalHeaderLabels(['point', 'direction', 'radius', ''])
        self.seed_table.verticalHeader().setVisible(False)
        self.seed_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.seed_table)
        self.pick_hint = QtWidgets.QLabel(''); self.pick_hint.setStyleSheet('color: #9a6700')
        lay.addWidget(self.pick_hint)

        row2 = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton('Save seeds'); self.save_btn.clicked.connect(self.save_seeds)
        self.run_btn = QtWidgets.QPushButton('▶ Segment and open outlets'); self.run_btn.clicked.connect(self.run_segment)
        row2.addStretch(); row2.addWidget(self.save_btn); row2.addWidget(self.run_btn)
        lay.addLayout(row2)
        self.message = QtWidgets.QLabel(''); self.message.setWordWrap(True)
        lay.addWidget(self.message)
        lay.addStretch()
        self._model_status()
        self._set_seeding_enabled(False)

    def _set_seeding_enabled(self, on: bool):
        """Seeds belong to a case, so they can only be placed once one exists."""
        for w in (self.pick_btn, self.save_btn, self.run_btn, self.radius, self.seed_table):
            w.setEnabled(on)
        if not on:
            self.pick_btn.setChecked(False)
        self.pick_hint.setText('' if on else 'Create the case from this image first, then place the seeds.')

    # ---- image ----------------------------------------------------------
    def _browse_image(self):
        f, _ = self.W.QFileDialog.getOpenFileName(self.main.win, 'Image volume', '',
                                                  'Volumes (*.nii *.nii.gz *.mha *.mhd *.nrrd *.nhdr *.vti *.vtk);;'
                                                  'All files (*)')
        if f:
            self.image_edit.setText(f)
            self.load_image(Path(f))

    def _browse_case_dir(self):
        d = self.W.QFileDialog.getExistingDirectory(self.main.win, 'Case folder', self.case_edit.text() or str(Path.home()))
        if d:
            self.case_edit.setText(d)

    def load_image(self, path: Path):
        import pyvista as pv
        if path.suffix.lower() in ('.vti', '.vtk'):             # VTK images: read them directly
            grid = pv.read(str(path))
            if not isinstance(grid, pv.ImageData):
                return self.main.error('%s is a %s, not an image volume' % (path.name, type(grid).__name__))
            name = grid.point_data.active_scalars_name or (list(grid.point_data.keys()) or [None])[0]
            if name is None:
                return self.main.error('%s carries no point data to show' % path.name)
            if name != 'intensity':
                grid.point_data['intensity'] = np.asarray(grid.point_data[name], dtype=np.float32)
            size, spacing = grid.dimensions, grid.spacing
        else:
            try:
                import SimpleITK as sitk
            except ImportError:
                return self.main.error('SimpleITK is needed to read images: pip install "miros[seg]"')
            img = sitk.ReadImage(str(path))
            arr = sitk.GetArrayFromImage(img)                   # z, y, x
            grid = pv.ImageData(dimensions=img.GetSize(), spacing=img.GetSpacing(), origin=img.GetOrigin())
            d = np.asarray(img.GetDirection()).reshape(3, 3)
            if hasattr(grid, 'direction_matrix'):
                grid.direction_matrix = d
            grid.point_data['intensity'] = arr.ravel(order='C').astype(np.float32)
            size, spacing = img.GetSize(), img.GetSpacing()
        self.image = grid
        self.image_path = path
        extent = max(np.asarray(size) * np.asarray(spacing))
        mm = extent > 60
        self.units.setCurrentText('mm' if mm else 'cm')
        self.units_hint.setText('extent %.1f, spacing %s → looks like %s' % (
            extent, 'x'.join('%.2f' % s for s in spacing), 'mm' if mm else 'cm'))
        self.radius.setValue(10.0 if mm else 1.0)
        if not self.case_edit.text():
            stem = path.name.split('.')[0]
            self.case_edit.setText(str(Path.home() / 'miros_cases' / stem))
        self.main.viewer.show_image(grid)
        self.main.status('loaded %s (%s)' % (path.name, 'x'.join(str(s) for s in size)))

    # ---- model ----------------------------------------------------------
    def _model_status(self):
        from ..models import find_model_folder
        name = self.model.currentData()
        ok = find_model_folder(name) is not None if name else False
        self.model_status.setText('ready' if ok else 'not downloaded')
        self.model_status.setStyleSheet('color: green' if ok else 'color: #b3261e')
        self.download_btn.setEnabled(not ok)

    def _download(self):
        from ..models import MODELS, download
        name = self.model.currentData()
        if self._download_thread is not None:
            return
        self.download_btn.setEnabled(False)
        self.model_status.setText('downloading… 0%')
        state = {'pct': 0.0, 'done': False, 'error': None}

        def progress(done, total):
            state['pct'] = 100.0 * done / total if total else 0.0

        def work():
            try:
                download(name, progress=progress)
            except Exception as e:                       # noqa: BLE001
                state['error'] = str(e)
            state['done'] = True

        self._download_thread = threading.Thread(target=work, daemon=True)
        self._download_thread.start()
        timer = self.QtCore.QTimer(self.widget)

        def tick():
            if state['done']:
                timer.stop()
                self._download_thread = None
                if state['error']:
                    self.main.error('download failed: %s' % state['error'])
                self._model_status()
            else:
                self.model_status.setText('downloading… %.0f%% (%.0f MB)' % (state['pct'], MODELS[name]['size'] / 1e6))
        timer.timeout.connect(tick)
        timer.start(250)

    # ---- case -----------------------------------------------------------
    def create_case(self):
        from ..config import write_template
        img = self.image_edit.text().strip()
        d = self.case_edit.text().strip()
        if not img or not Path(img).exists():
            return self.main.error('choose an existing image file')
        if not d:
            return self.main.error('choose a case folder')
        d = Path(d).resolve()
        d.mkdir(parents=True, exist_ok=True)
        y = d / 'case.yaml'
        if y.exists() and not self.main.offscreen:
            r = self.W.QMessageBox.question(self.main.win, 'MIROS', '%s exists. Open it instead?' % y)
            if r == self.W.QMessageBox.Yes:
                return self.main.load_case(d)
            return
        from ..cli import _case_relative
        write_template(y, name=d.name, surface=None, units=self.units.currentText(), inlet=None,
                       inflow_file='input/inflow.flow', inflow_source='gui', outlet_names=None,
                       image=_case_relative(Path(img).resolve(), d), image_units=self.units.currentText(),
                       seg_model=self.model.currentData())
        self.main.load_case(d, show_model=False)
        self._set_seeding_enabled(True)
        self.main.status('created %s' % y)
        self.message.setText('case created — now place the seeds and press Segment')

    def load_from_case(self):
        """Fill the page from the loaded case's segmentation section."""
        case = self.main.case
        sg = case.config.segmentation
        if not sg.image:
            return
        self.image_edit.setText(str(case.resolve(sg.image)))
        self.case_edit.setText(str(case.dir))
        self.units.setCurrentText(sg.units)
        i = self.model.findData(sg.model)
        if i >= 0:
            self.model.setCurrentIndex(i)
        self.seeds = [dict(point=list(s.point), direction=list(s.direction), radius=float(s.radius)) for s in sg.seeds]
        self._set_seeding_enabled(True)
        self._refresh_seed_table()
        if self.image is None or self.image_path != case.resolve(sg.image):
            try:
                self.load_image(case.resolve(sg.image))
            except Exception as e:                       # noqa: BLE001
                self.main.error(str(e))
        self.main.viewer.show_seeds(self.seeds)

    # ---- seeds ----------------------------------------------------------
    def _toggle_pick(self, on):
        if on and self.main.case is None:
            self.pick_btn.setChecked(False)
            return self.main.error('create the case from this image first (button above), then place the seeds')
        if self.image is None:
            self.pick_btn.setChecked(False)
            return self.main.error('load an image first')
        if self.main.viewer._image is not self.image:      # only when something else was on screen
            self.main.viewer.show_image(self.image)
        self.main.viewer.show_seeds(self.seeds)
        if on:
            self.pending = None
            self.pick_hint.setText('click the START point on a slice')
            self.main.viewer.enable_slice_picking(self._picked_point)
        else:
            self.pick_hint.setText('')
            self.main.viewer.disable_pick()

    def _picked_point(self, point):
        p = [float(v) for v in np.asarray(point).ravel()[:3]]
        if self.pending is None:
            self.pending = p
            self.pick_hint.setText('start %s — now click the DIRECTION point, a little further along the vessel' % np.round(p, 2).tolist())
            self.main.viewer.show_seeds(self.seeds, pending=p)
            return
        self.seeds.append(dict(point=self.pending, direction=p, radius=float(self.radius.value())))
        self.pending = None
        self.pick_hint.setText('seed added — click for another START point, or untick the button')
        self._refresh_seed_table()
        self.main.viewer.show_seeds(self.seeds)

    def _refresh_seed_table(self):
        W = self.W
        self.seed_table.setRowCount(len(self.seeds))
        for r, s in enumerate(self.seeds):
            self.seed_table.setItem(r, 0, W.QTableWidgetItem(', '.join('%.2f' % v for v in s['point'])))
            self.seed_table.setItem(r, 1, W.QTableWidgetItem(', '.join('%.2f' % v for v in s['direction'])))
            self.seed_table.setItem(r, 2, W.QTableWidgetItem('%.2f' % s['radius']))
            b = W.QPushButton('remove')
            b.clicked.connect(lambda _=False, i=r: self._remove_seed(i))
            self.seed_table.setCellWidget(r, 3, b)

    def _remove_seed(self, i):
        if 0 <= i < len(self.seeds):
            del self.seeds[i]
            self._refresh_seed_table()
            self.main.viewer.show_seeds(self.seeds)

    def save_seeds(self):
        from ..config_edit import set_seeds, set_values
        if self.main.case is None:
            return self.main.error('create the case first')
        if not self.seeds:
            return self.main.error('place at least one seed')
        set_values(self.main.case.yaml, {'segmentation.units': self.units.currentText(),
                                         'segmentation.model': self.model.currentData()})
        set_seeds(self.main.case.yaml, self.seeds)
        self.main.refresh_status()
        self.message.setText('saved %d seed(s) to %s' % (len(self.seeds), self.main.case.yaml))
        self.main.status('seeds saved')

    def run_segment(self):
        from ..models import find_model_folder
        if self.main.case is None:
            return self.main.error('create the case first')
        if not self.seeds:
            return self.main.error('place at least one seed')
        if find_model_folder(self.model.currentData()) is None:
            return self.main.error('download the model first')
        self.save_seeds()
        self.pick_btn.setChecked(False)
        self.main.start_run(None, False, until='preprocess', on_done=self._segment_done)

    def _segment_done(self, ok):
        if ok:
            self.main.load_case(self.main.case.dir)
            self.main.tabs.setCurrentIndex(self.main.TAB_MODEL)
            self.main.status('segmentation done — caps detected, continue with the inflow')
