"""
`miros gui`: the whole workflow in one window.

Left, always: the 3D model in the `miros show caps` style (light-gray
wall, crimson inlet, steel-blue outlets, labels with name and area), later
also the 1D results painted onto the vessels.

Right, as steps:
    1 Model     pick the clipped surface (and units), create or open the case
    2 Inflow    draw one cardiac cycle on an embedded editor, or load a file
    3 Targets   name caps, choose the inlet, flow shares, pressure anchor/targets
    4 Run       run the stale stages in the background with a live log
    5 Results   per-outlet numbers, the 0D plot, and 1D pressure/flow on the 3D view

Needs the GUI extra: pip install pyvistaqt PySide6
"""
import contextlib
import io
import json
import os
import re
import shutil
import sys
import traceback
from pathlib import Path
from typing import List, Optional

import numpy as np

from ..config import STAGES
from ..timestep import recommended_samples_per_cycle

_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')


def _require_qt():
    try:
        import pyvistaqt  # noqa: F401
        import qtpy  # noqa: F401
    except ImportError:
        raise RuntimeError("the MIROS window needs the GUI extra: pip install pyvistaqt PySide6")


# ============================================================================
# 3D view

class Viewer:
    """The QtInteractor with the `show caps` styling; None-safe when offscreen."""

    WALL = dict(color='lightgray', opacity=0.5)
    INLET, OUTLET, SELECTED = 'crimson', 'steelblue', 'gold'

    def __init__(self, parent, offscreen: bool):
        self.plotter = None
        self.widget = None
        self.actors = {}
        self._pick_cb = None
        self._click_filter = None
        self._image = None            # the volume currently sliced on screen (Segment step)
        self._camera_set = False
        self._results = None          # cache of the loaded 1D results (see load_results)
        if not offscreen:
            from pyvistaqt import QtInteractor
            self.plotter = QtInteractor(parent)
            self.widget = self.plotter.interactor

    @property
    def can_pick(self):
        return self.plotter is not None and getattr(self.plotter, 'iren', None) is not None

    def clear(self):
        if self.plotter is not None:
            if self.can_pick:
                self.disable_pick()                      # pyvista refuses to enable picking twice
            self.plotter.clear()
            self.plotter.clear_slider_widgets()
        self.actors = {}
        self._image = None

    def show_model(self, surf, caps, names: List[str], inlet_row: int, selected: Optional[int] = None,
                   pick_callback=None):
        if self.plotter is None:
            return
        import pyvista as pv
        self.clear()
        self.plotter.add_mesh(pv.wrap(surf), name='wall', **self.WALL)
        for i, c in enumerate(caps):
            color = self.SELECTED if i == selected else (self.INLET if i == inlet_row else self.OUTLET)
            self.actors[i] = self.plotter.add_mesh(pv.wrap(c.polydata), color=color, opacity=0.9, name='cap%d' % i)
        self.labels(caps, names, inlet_row)
        if pick_callback is not None and self.can_pick:
            self._pick_cb = pick_callback
            self.plotter.enable_mesh_picking(callback=pick_callback, show=False, show_message=False, left_clicking=True)
            self.plotter.add_text('click a cap to select it', position='lower_left', font_size=10, name='hint')
        if not self._camera_set:
            self.plotter.reset_camera()
            self._camera_set = True
        self.plotter.render()

    def labels(self, caps, names, inlet_row):
        if self.plotter is None:
            return
        pts = np.array([c.centroid + 1.5 * c.radius * c.normal for c in caps])
        txt = ['%s%s\n%.3f cm²' % (names[i], ' (inlet)' if i == inlet_row else '', c.area) for i, c in enumerate(caps)]
        self.plotter.add_point_labels(pts, txt, name='labels', font_size=12, point_size=0, shape_opacity=0.6,
                                      always_visible=True)

    def highlight(self, caps, inlet_row, selected):
        if self.plotter is None or not self.actors:
            return
        for i, c in enumerate(caps):
            self.actors[i].prop.color = self.SELECTED if i == selected else (self.INLET if i == inlet_row else self.OUTLET)
        self.plotter.render()

    # ---- image slices and seeds (Segment step) ----------------------------
    def show_image(self, grid):
        """
        Three orthogonal slices of a volume, with a slider each.

        The slices are vtkImageActors: the mapper uploads the one plane it
        shows, so moving a slider is a display-extent change (about a
        millisecond) instead of cutting a polygonal slice out of the volume
        (about a second on a 512x64x512 scan).
        """
        if self.plotter is None:
            return
        import vtk
        self.clear()
        self._image = grid
        dims = np.array(grid.dimensions, dtype=int) - 1
        origin, spacing = np.array(grid.origin, float), np.array(grid.spacing, float)
        b = grid.bounds
        lo, hi = np.array(b[0::2], float), np.array(b[1::2], float)
        vals = np.asarray(grid.point_data['intensity'])
        step = max(int(vals.size // 2_000_000), 1)        # a sample is enough for the grey range
        c0, c1 = (float(np.percentile(vals[::step], 1)), float(np.percentile(vals[::step], 99)))

        self._slice_actors = []
        for axis in range(3):
            a = vtk.vtkImageActor()
            a.GetMapper().SetInputData(grid)
            a.GetProperty().SetColorWindow(max(c1 - c0, 1e-6))
            a.GetProperty().SetColorLevel(0.5 * (c0 + c1))
            a.GetProperty().SetInterpolationTypeToLinear()
            self.plotter.add_actor(a, name='slice_%d' % axis)
            self._slice_actors.append(a)

        def set_plane(axis, world):
            k = int(round((world - origin[axis]) / max(spacing[axis], 1e-12)))
            k = int(np.clip(k, 0, dims[axis]))
            e = [0, dims[0], 0, dims[1], 0, dims[2]]
            e[2 * axis] = e[2 * axis + 1] = k
            self._slice_actors[axis].SetDisplayExtent(*e)

        self._set_plane = set_plane
        for axis in range(3):
            set_plane(axis, 0.5 * (lo[axis] + hi[axis]))
        for axis, (name, y0) in enumerate((('x', 0.10), ('y', 0.16), ('z', 0.22))):
            self.plotter.add_slider_widget(lambda v, a=axis: (set_plane(a, v), self.plotter.render()),
                                           rng=(lo[axis], hi[axis]), value=0.5 * (lo[axis] + hi[axis]), title=name,
                                           pointa=(0.02, y0), pointb=(0.22, y0), style='modern', title_height=0.015,
                                           slider_width=0.015, tube_width=0.004, fmt='%.1f')
        self.plotter.add_axes()
        if not self._camera_set:
            self.plotter.reset_camera()
            self._camera_set = True
        self.plotter.render()

    def show_seeds(self, seeds, pending=None):
        if self.plotter is None:
            return
        import pyvista as pv
        self.plotter.remove_actor('seeds', render=False)
        self.plotter.remove_actor('seed_dirs', render=False)
        self.plotter.remove_actor('seed_pending', render=False)
        self.plotter.remove_actor('seed_labels', render=False)
        if seeds:
            pts = np.array([s['point'] for s in seeds])
            self.plotter.add_mesh(pv.PolyData(pts), name='seeds', color='crimson', point_size=14, render_points_as_spheres=True)
            lines = [pv.Line(s['point'], s['direction']) for s in seeds]
            self.plotter.add_mesh(pv.merge(lines), name='seed_dirs', color='gold', line_width=4)
            self.plotter.add_point_labels(pts, ['seed %d (r %.2f)' % (i + 1, s['radius']) for i, s in enumerate(seeds)],
                                          name='seed_labels', font_size=11, point_size=0, shape_opacity=0.6, always_visible=True)
        if pending is not None:
            self.plotter.add_mesh(pv.PolyData(np.array([pending])), name='seed_pending', color='orange', point_size=14,
                                  render_points_as_spheres=True)
        self.plotter.render()

    def enable_slice_picking(self, callback):
        """
        Click a slice to report the 3D point under the cursor. VTK gives the
        rotation style exclusive focus between press and release, so the
        click is caught on the Qt widget instead: a plain click places a
        point, a drag turns the view as usual.
        """
        if not self.can_pick or self.widget is None:
            return
        import vtk
        from qtpy import QtCore
        self.disable_pick()
        widget, plotter = self.widget, self.plotter
        picker = vtk.vtkCellPicker()
        picker.SetTolerance(0.005)

        class _ClickFilter(QtCore.QObject):
            def __init__(self):
                super().__init__(widget)
                self.pressed_at = None

            def eventFilter(self, obj, ev):
                t = ev.type()
                if t == QtCore.QEvent.MouseButtonPress and ev.button() == QtCore.Qt.LeftButton:
                    self.pressed_at = ev.pos()
                elif t == QtCore.QEvent.MouseButtonRelease and ev.button() == QtCore.Qt.LeftButton:
                    at, self.pressed_at = self.pressed_at, None
                    if at is not None and (ev.pos() - at).manhattanLength() <= 4:
                        self.pick(ev.pos())
                return False                      # never swallow the event: VTK still gets it

            def pick(self, pos):
                w = plotter.render_window.GetSize()                 # device pixels
                r = w[0] / max(widget.width(), 1)                   # HiDPI / device pixel ratio
                x, y = int(pos.x() * r), int(w[1] - 1 - pos.y() * r)
                if picker.Pick(x, y, 0, plotter.renderer):
                    callback(np.array(picker.GetPickPosition()))

        self._click_filter = _ClickFilter()
        widget.installEventFilter(self._click_filter)
        self.plotter.add_text('click a slice to place a seed point (drag still turns the view)',
                              position='lower_left', font_size=10, name='hint')

    def disable_pick(self):
        if not self.can_pick:
            return
        f = getattr(self, '_click_filter', None)
        if f is not None and self.widget is not None:
            self.widget.removeEventFilter(f)
        self._click_filter = None
        try:
            self.plotter.disable_picking()
        except Exception:
            pass
        self.plotter.remove_actor('hint', render=True)

    # ---- 1D results ------------------------------------------------------
    UNITS = {'pressure_mmHg': 'mmHg', 'flow': 'mL/s', 'area': 'cm²'}

    def load_results(self, vtp_path, surf):
        """
        Read the 1D result file once: the centerline (as polylines), the
        per-time arrays of every quantity, and the map from each wall point
        to its nearest centerline point.
        """
        import pyvista as pv
        from scipy.spatial import cKDTree
        vtp_path = Path(vtp_path)
        key = (str(vtp_path), vtp_path.stat().st_mtime)
        if self._results is not None and self._results.get('key') == key:
            return self._results
        cl = pv.read(str(vtp_path))
        stacks, times = {}, None
        for q in ('pressure_mmHg', 'flow', 'area'):
            keys = [k for k in cl.point_data.keys() if k.startswith(q + '_')]
            if not keys:
                continue
            t = np.array([float(k[len(q) + 1:]) for k in keys])
            order = np.argsort(t)
            stacks[q] = np.stack([np.asarray(cl.point_data[keys[i]], dtype=np.float32) for i in order], axis=0)
            times = t[order]
        if not stacks:
            raise RuntimeError("no per-time result arrays in %s" % vtp_path)
        base = pv.PolyData(cl.points.copy())
        base.lines = cl.lines
        base = base.strip()                                   # 2-point cells -> polylines (points unchanged)
        base.point_data['orig'] = np.arange(cl.n_points)
        base.point_data['r'] = (np.asarray(cl.point_data['MaximumInscribedSphereRadius'])
                                if 'MaximumInscribedSphereRadius' in cl.point_data else np.full(cl.n_points, 0.15))
        tube = base.tube(scalars='r', absolute=True, n_sides=12, capping=True)
        tube_idx = np.asarray(tube.point_data['orig']).round().astype(int)
        wall = pv.wrap(surf).copy() if surf is not None else None
        wall_idx = cKDTree(cl.points).query(wall.points)[1] if wall is not None else None
        self._results = dict(key=key, times=times, stacks=stacks, tube=tube, tube_idx=tube_idx,
                             wall=wall, wall_idx=wall_idx,
                             clim={q: (float(np.nanmin(s)), float(np.nanmax(s))) for q, s in stacks.items()})
        return self._results

    def show_results(self, vtp_path, quantity: str = 'pressure_mmHg', on: str = 'surface', mean: bool = False, surf=None):
        """
        Colour the model by a 1D result: on the wall (each wall point takes the
        value of its nearest centerline point) or on the centerline as a tube.
        A slider scrubs the last cycle; `mean` shows the cycle average.
        """
        if self.plotter is None:
            return
        res = self.load_results(vtp_path, surf)
        if quantity not in res['stacks']:
            raise RuntimeError("no %s in the 1D results" % quantity)
        stack, times, clim = res['stacks'][quantity], res['times'], res['clim'][quantity]
        if on == 'surface' and res['wall'] is not None:
            mesh, idx = res['wall'], res['wall_idx']
        else:
            mesh, idx = res['tube'], res['tube_idx']
        unit = self.UNITS.get(quantity, '')
        title = '%s [%s]' % (quantity.replace('_mmHg', ''), unit)
        # rebuild the scene without dropping the cached results
        keep = self._results
        self.clear()
        self._results = keep
        if on != 'surface' and surf is not None:
            self.plotter.add_mesh(res['wall'], name='wall', color='lightgray', opacity=0.12)
        mesh.point_data['value'] = stack[-1][idx]
        self.plotter.add_mesh(mesh, name='results', scalars='value', clim=clim, cmap='coolwarm', smooth_shading=True,
                              scalar_bar_args=dict(title=title, vertical=True, position_x=0.86, position_y=0.15,
                                                   height=0.7, width=0.06, title_font_size=14, label_font_size=12))
        state = {'i': len(times) - 1}

        def draw(i):
            i = int(np.clip(round(i), 0, len(times) - 1))
            state['i'] = i
            mesh.point_data['value'] = stack[i][idx]
            self.plotter.add_text('t = %.3f s' % (times[i] - times[0]), position='upper_left', font_size=11, name='time')
            self.plotter.render()

        if mean:
            mesh.point_data['value'] = stack.mean(axis=0)[idx]
            self.plotter.add_text('cycle mean', position='upper_left', font_size=11, name='time')
        else:
            draw(state['i'])
            self.plotter.add_slider_widget(draw, rng=(0, len(times) - 1), value=state['i'], title='time step',
                                           style='modern', pointa=(0.12, 0.07), pointb=(0.62, 0.07), fmt='%.0f',
                                           title_height=0.02, slider_width=0.02, tube_width=0.006)
        self.plotter.add_text('1D %s on the %s' % (quantity.replace('_mmHg', ''), 'wall' if on == 'surface' else 'centerline'),
                              position='lower_left', font_size=10, name='hint')
        self.plotter.render()


# ============================================================================
# background run

class _RunEmitter:
    """Created lazily so the module imports without Qt."""

    @staticmethod
    def make():
        from qtpy import QtCore

        class Emitter(QtCore.QObject):
            line = QtCore.Signal(str)
            stage = QtCore.Signal(str, str)
            done = QtCore.Signal(bool, str)
        return Emitter()


class _LineWriter(io.TextIOBase):
    def __init__(self, emit):
        super().__init__()
        self.emit = emit
        self.buf = ''

    def write(self, s):
        self.buf += s
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1)
            self.emit(line)
        return len(s)

    def flush(self):
        if self.buf:
            self.emit(self.buf)
            self.buf = ''


def run_case_blocking(case_dir, from_stage, force, emit_line, emit_stage, until=None) -> None:
    """The pipeline with plain-text console output routed to emit_line; raises on failure."""
    from ..case import Case
    from . import console
    w = _LineWriter(emit_line)
    console.set_plain(True)                  # no ANSI colours / box drawing in the log pane
    console.set_interactive(False)           # a stage must never open a blocking window in this thread
    try:
        with contextlib.redirect_stdout(w), contextlib.redirect_stderr(w):
            Case(case_dir).run(from_stage=from_stage, until=until, force=force, progress=emit_stage)
    finally:
        w.flush()
        console.set_plain(False)


# ============================================================================
# main window

class MainWindow:
    TAB_SEGMENT, TAB_MODEL, TAB_INFLOW, TAB_TARGETS, TAB_RUN, TAB_RESULTS = range(6)

    def __init__(self, case_dir=None, offscreen: bool = False, start_tab: int = 1):
        _require_qt()
        from qtpy import QtCore, QtWidgets, QtGui
        self.QtCore, self.W, self.QtGui = QtCore, QtWidgets, QtGui
        self.offscreen = offscreen

        self.case = None
        self.surf = None
        self.caps = []
        self.names: List[str] = []
        self.inlet_row = 0
        self.selected = None
        self.worker = None

        owner = self

        class _Main(QtWidgets.QMainWindow):
            def closeEvent(self, ev):                       # never destroy a running worker thread
                if owner.worker is not None and owner.worker.isRunning():
                    r = QtWidgets.QMessageBox.question(self, 'MIROS', 'A run is in progress. Wait for it to finish?')
                    if r == QtWidgets.QMessageBox.Yes:
                        owner.worker.wait()
                    else:
                        ev.ignore()
                        return
                ev.accept()

        self.win = _Main()
        self.win.setWindowTitle('MIROS')
        split = QtWidgets.QSplitter()
        self.win.setCentralWidget(split)
        self.viewer = Viewer(split, offscreen)
        if self.viewer.widget is not None:
            split.addWidget(self.viewer.widget)
        self.tabs = QtWidgets.QTabWidget()
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        from .segment_page import SegmentPage
        self.segment = SegmentPage(self)
        self.tabs.addTab(self.segment.widget, '0  Segment')
        self._build_model_tab()
        self._build_inflow_tab()
        self._build_bc_tab()
        self._build_run_tab()
        self._build_results_tab()
        self._enable_tabs(False)
        self.win.resize(1400, 800)
        self.win.statusBar()
        self.tabs.setCurrentIndex(self.TAB_MODEL)

        if case_dir is not None:
            self.load_case(Path(case_dir))
            self.tabs.setCurrentIndex(start_tab)

    # ------------------------------------------------------------ helpers
    def _enable_tabs(self, loaded: bool):
        for i in (self.TAB_INFLOW, self.TAB_TARGETS, self.TAB_RUN, self.TAB_RESULTS):
            self.tabs.setTabEnabled(i, loaded)
        if hasattr(self, 'model_next'):
            self.model_next.setEnabled(loaded)
            self.model_next_hint.setText('' if loaded else 'Create a case from the surface (or from an image on the '
                                                            'Segment step), or open an existing one, to continue.')

    def status(self, msg: str):
        self.win.statusBar().showMessage(msg, 8000)

    def error(self, msg: str):
        if self.offscreen:
            self.last_error = msg
            return
        self.W.QMessageBox.critical(self.win, 'MIROS', msg)

    def _next_button(self, layout, label='Next ▶', to=None):
        b = self.W.QPushButton(label)
        b.clicked.connect(lambda: self.tabs.setCurrentIndex(to if to is not None else self.tabs.currentIndex() + 1))
        row = self.W.QHBoxLayout()
        row.addStretch()
        row.addWidget(b)
        layout.addLayout(row)
        return b

    # ------------------------------------------------------------ 1 model
    def _build_model_tab(self):
        W = self.W
        page = W.QWidget()
        lay = W.QVBoxLayout(page)
        lay.addWidget(W.QLabel('<b>Start from a clipped model</b><br>The surface must be open at the inlet and at every outlet.'))
        form = W.QFormLayout()
        self.surface_edit = W.QLineEdit()
        b1 = W.QPushButton('Browse…'); b1.clicked.connect(self._browse_surface)
        r1 = W.QHBoxLayout(); r1.addWidget(self.surface_edit); r1.addWidget(b1)
        form.addRow('surface (.vtp/.stl/.ply)', r1)
        self.units = W.QComboBox(); self.units.addItems(['cm', 'mm'])
        self.units_hint = W.QLabel(''); self.units_hint.setStyleSheet('color: gray')
        r2 = W.QHBoxLayout(); r2.addWidget(self.units); r2.addWidget(self.units_hint); r2.addStretch()
        form.addRow('units', r2)
        self.case_edit = W.QLineEdit()
        b2 = W.QPushButton('Browse…'); b2.clicked.connect(self._browse_case_dir)
        r3 = W.QHBoxLayout(); r3.addWidget(self.case_edit); r3.addWidget(b2)
        form.addRow('case folder', r3)
        lay.addLayout(form)
        row = W.QHBoxLayout()
        self.create_btn = W.QPushButton('Create case from this surface')
        self.create_btn.clicked.connect(self.create_case)
        open_btn = W.QPushButton('Open existing case…')
        open_btn.clicked.connect(self._open_case_dialog)
        row.addWidget(self.create_btn); row.addWidget(open_btn); row.addStretch()
        lay.addLayout(row)
        self.model_info = W.QLabel(''); self.model_info.setWordWrap(True)
        lay.addWidget(self.model_info)
        lay.addStretch()
        self.model_next_hint = W.QLabel(''); self.model_next_hint.setStyleSheet('color: #9a6700')
        lay.addWidget(self.model_next_hint)
        self.model_next = self._next_button(lay)
        self.model_next.setEnabled(False)
        self.model_next_hint.setText('Create a case from the surface, or open an existing one, to continue.')
        self.tabs.addTab(page, '1  Model')

    def _browse_surface(self):
        f, _ = self.W.QFileDialog.getOpenFileName(self.win, 'Clipped surface', '', 'Surfaces (*.vtp *.stl *.ply)')
        if f:
            self.surface_edit.setText(f)
            self._suggest_from_surface(Path(f))

    def _suggest_from_surface(self, f: Path):
        from ..geometry import caps as C
        try:
            surf = C.read_polydata(f)
            b = surf.GetBounds()
            size = max(b[1] - b[0], b[3] - b[2], b[5] - b[4])
            mm = size > 60
            self.units.setCurrentText('mm' if mm else 'cm')
            self.units_hint.setText('largest extent %.1f → looks like %s' % (size, 'mm' if mm else 'cm'))
        except Exception as e:
            self.units_hint.setText(str(e)[:80])
        if not self.case_edit.text():
            self.case_edit.setText(str(Path.home() / 'miros_cases' / f.stem))

    def _browse_case_dir(self):
        d = self.W.QFileDialog.getExistingDirectory(self.win, 'Case folder', self.case_edit.text() or str(Path.home()))
        if d:
            self.case_edit.setText(d)

    def _open_case_dialog(self):
        d = self.W.QFileDialog.getExistingDirectory(self.win, 'Open case folder', str(Path.home()))
        if d:
            self.load_case(Path(d))

    def create_case(self):
        from ..config import write_template
        from ..geometry import caps as C
        surface = self.surface_edit.text().strip()
        case_dir = self.case_edit.text().strip()
        if not surface or not Path(surface).exists():
            return self.error('choose an existing surface file')
        if not case_dir:
            return self.error('choose a case folder')
        d = Path(case_dir).resolve()
        d.mkdir(parents=True, exist_ok=True)
        y = d / 'case.yaml'
        if y.exists():
            if not self.offscreen:
                r = self.W.QMessageBox.question(self.win, 'MIROS', '%s exists. Open it instead?' % y)
                if r == self.W.QMessageBox.Yes:
                    return self.load_case(d)
                return
        try:
            caps = C.make_caps(C.read_polydata(surface))
        except Exception as e:
            return self.error(str(e))
        from ..cli import _case_relative
        rel = _case_relative(Path(surface).resolve(), d)
        write_template(y, name=d.name, surface=rel, units=self.units.currentText(), inlet=C.inlet_cap(caps).name,
                       inflow_file='input/inflow.flow', inflow_source='gui',
                       outlet_names=[c.name for c in C.outlet_caps(caps)])
        self.load_case(d)
        self.status('created %s' % y)

    def load_case(self, d: Path, show_model: bool = True):
        from ..case import Case
        from ..config import ConfigError
        from ..geometry import caps as C
        try:
            self.case = Case(d)
        except (ConfigError, FileNotFoundError) as e:
            return self.error(str(e))
        m = self.case.config.model
        self.win.setWindowTitle('MIROS — %s' % self.case.config.name)
        self.case_edit.setText(str(self.case.dir))
        if self.case.config.segmentation.image:
            # an image case: the caps exist only once the segment + preprocess stages have run
            self.segment.load_from_case()
            if not (self.case.surface_work.exists() and self.case.caps_json.exists()):
                self.caps, self.names, self.surf = [], [], None
                self._enable_tabs(False)
                self.tabs.setTabEnabled(self.TAB_RUN, True)
                self.model_info.setText('<b>%s</b> — image case: place the seeds on the Segment step and run it '
                                        'to get the caps.' % self.case.config.name)
                self.refresh_status()
                return
            src = self.case.surface_work
            info = self.case.caps_info()
            inlet, names = info['inlet'], info['names_by_area']
        else:
            src = self.case.resolve(m.surface)
            inlet, names = m.inlet, m.cap_names
        try:
            self.surf = C.read_polydata(src)
            caps = C.make_caps(self.surf, inlet=inlet, names=names)
        except Exception as e:
            return self.error(str(e))
        caps.sort(key=lambda c: -c.area)
        self.caps = caps
        self.names = [c.name for c in caps]
        self.inlet_row = next(i for i, c in enumerate(caps) if c.is_inlet)
        self.selected = None
        self.surface_edit.setText(str(src))
        self.units.setCurrentText(m.units)
        self.model_info.setText('<b>%s</b> — %d caps, inlet %s, units %s<br>%s' % (
            self.case.config.name, len(caps), self.names[self.inlet_row], m.units, self.case.yaml))
        self._enable_tabs(True)
        if show_model:
            self.viewer.show_model(self.surf, self.caps, self.names, self.inlet_row, pick_callback=self._picked)
        self._fill_bc_form()
        self._load_inflow_into_editor()
        self.refresh_status()
        self._fill_results()

    # ------------------------------------------------------------ 2 inflow
    def _build_inflow_tab(self):
        W = self.W
        page = W.QWidget()
        lay = W.QVBoxLayout(page)
        lay.addWidget(W.QLabel('<b>One cardiac cycle of inflow</b> — drag the red points; first and last are tied.'))
        import matplotlib
        matplotlib.use('QtAgg', force=True)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        import matplotlib.ticker as mticker
        from scipy.interpolate import interp1d
        from .waveform_editor import _DraggablePoints
        self.fig = Figure(figsize=(6, 3.6))
        self.canvas = FigureCanvasQTAgg(self.fig)
        ax = self.fig.add_subplot(111)
        self.ax = ax
        self.x_ctrl = np.linspace(0, 1, 20)
        self.y_ctrl = np.zeros(20)
        self.x_dense = np.linspace(0, 1, 500)
        self.line, = ax.plot(self.x_dense, np.zeros(500), lw=2)
        ax.grid(True, alpha=0.3); ax.set_ylabel('Flow [mL/s]'); ax.set_xlabel('cycle')
        ax.set_xlim(0, 1); ax.set_ylim(-100, 500)
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, p: '%d%%' % round(v * 100)))
        self.fig.tight_layout()

        def refresh():
            f = interp1d(self.x_ctrl, self.y_ctrl, kind='quadratic', fill_value='extrapolate')
            self.line.set_data(self.x_dense, f(self.x_dense))
            self.inflow_edited = True
            self._inflow_summary()
        self.dragger = _DraggablePoints(ax, self.x_ctrl, self.y_ctrl, refresh)
        lay.addWidget(self.canvas, 1)
        form = W.QFormLayout()
        self.hr = W.QDoubleSpinBox(); self.hr.setRange(20, 250); self.hr.setValue(70); self.hr.setDecimals(1)
        self.hr.valueChanged.connect(lambda *_: (setattr(self, 'inflow_edited', True), self._inflow_summary()))
        form.addRow('heart rate [bpm]', self.hr)
        self.peak = W.QDoubleSpinBox(); self.peak.setRange(1, 5000); self.peak.setValue(400); self.peak.setDecimals(0)
        self.peak.setToolTip('sets the vertical range of the editor: -25% .. +125% of this value')
        self.peak.valueChanged.connect(self._rescale_axis)
        form.addRow('expected peak flow [mL/s]', self.peak)
        self.npts = W.QSpinBox(); self.npts.setRange(50, 50000); self.npts.setValue(1200); self.npts.setSingleStep(100)
        self.npts.setToolTip('The waveform is saved with this many time samples per cycle and the 0D and 1D solvers '
                             'use that spacing as their time step. The recommendation keeps the 1D Courant number '
                             '(v_peak + wave speed) * dt / dx below 0.8, with dx the smallest vessel diameter. '
                             'svOneDSolver is implicit, so smaller counts still run; the recommendation is about '
                             'accuracy, and the 1D run time grows with it.')
        self.dt_label = W.QLabel(''); self.dt_label.setStyleSheet('color: gray')
        self.npts.valueChanged.connect(lambda *_: (setattr(self, 'inflow_edited', True), self._inflow_summary()))
        r = W.QHBoxLayout(); r.addWidget(self.npts); r.addWidget(self.dt_label); r.addStretch()
        form.addRow('time samples per cycle', r)
        lay.addLayout(form)
        rec_row = W.QHBoxLayout()
        self.rec_label = W.QLabel(''); self.rec_label.setWordWrap(True)
        self.rec_btn = W.QPushButton('Use recommended'); self.rec_btn.clicked.connect(self._use_recommended)
        rec_row.addWidget(self.rec_label, 1); rec_row.addWidget(self.rec_btn)
        lay.addLayout(rec_row)
        self.recommended = None
        row = W.QHBoxLayout()
        load = W.QPushButton('Load .flow file…'); load.clicked.connect(self._load_inflow_file)
        self.save_inflow_btn = W.QPushButton('Use this waveform'); self.save_inflow_btn.clicked.connect(self.save_inflow)
        row.addWidget(load); row.addStretch(); row.addWidget(self.save_inflow_btn)
        lay.addLayout(row)
        self.inflow_info = W.QLabel(''); self.inflow_info.setWordWrap(True)
        lay.addWidget(self.inflow_info)
        self._next_button(lay)
        self.tabs.addTab(page, '2  Inflow')

    def _rescale_axis(self, v):
        self.ax.set_ylim(-0.25 * v, 1.25 * v)
        self.canvas.draw_idle()

    def _inflow_summary(self):
        t, q = self.waveform()
        tz = getattr(np, 'trapezoid', None) or np.trapz
        self.inflow_info.setText('cycle %.3f s · mean %.1f mL/s · peak %.1f mL/s · min %.1f mL/s' % (
            t[-1], tz(q, t) / (t[-1] - t[0]), q.max(), q.min()))
        self.dt_label.setText('→ solver time step %.2f ms' % (1000.0 * t[-1] / (len(t) - 1)))
        self._update_recommendation(t[-1], float(np.abs(q).max()))

    def _update_recommendation(self, cycle_s, q_peak):
        if self.case is None or not self.caps or q_peak <= 0:
            self.rec_label.setText('recommendation appears once a case with caps is loaded')
            self.rec_btn.setEnabled(False)
            return
        s = self.case.config.simulation
        m = s.material
        inlet = self.caps[self.inlet_row]
        n, d = recommended_samples_per_cycle(cycle_s, q_peak, inlet.area, min(c.area for c in self.caps),
                                             m.olufsen_k1, m.olufsen_k2, m.olufsen_k3, s.density)
        self.recommended = n
        self.rec_btn.setEnabled(True)
        self.rec_label.setText(
            '<b>Recommended: %d samples per cycle</b> (Δt %.2f ms) to keep the 1D Courant number below %.1f — '
            'peak inlet velocity %.0f cm/s + wave speed %.0f cm/s over the smallest vessel diameter %.2f cm. '
            '<span style="color:gray">1200 is the fast setting; the solvers are implicit and run stably with it.</span>'
            % (n, d['dt_ms'], d['cfl'], d['v_peak'], d['wave_speed'], d['dx']))

    def _use_recommended(self):
        if self.recommended:
            self.npts.setValue(int(self.recommended))

    def waveform(self):
        from scipy.interpolate import interp1d
        T = 60.0 / self.hr.value()
        t = np.linspace(0.0, T, int(self.npts.value()))
        f = interp1d(self.x_ctrl * T, self.y_ctrl, kind='quadratic', fill_value='extrapolate')
        return t, f(t)

    def _set_waveform(self, t, q):
        # the editor holds 20 control knots: showing a measured waveform is lossy, so
        # loading one must not count as an edit (save_inflow keeps the file untouched)
        T = t[-1] - t[0]
        self.hr.setValue(round(60.0 / T, 1))
        self.y_ctrl[:] = np.interp(self.x_ctrl, (t - t[0]) / T, q)
        self.peak.setValue(max(float(np.abs(q).max()), 1.0))
        self.dragger.pts.set_offsets(np.c_[self.x_ctrl, self.y_ctrl])
        self.dragger.update()
        self.canvas.draw_idle()
        self.inflow_edited = False

    def _inflow_target(self) -> Path:
        i = self.case.config.inflow
        return self.case.resolve(i.file) if i.file else self.case.dir / 'input' / 'inflow.flow'

    def _load_inflow_into_editor(self):
        from ..io.inflow import read_inflow
        f = self._inflow_target()
        if f.exists():
            t, q = read_inflow(f)
            self._set_waveform(t, q)
            self.inflow_info.setText('loaded %s' % f)
        else:
            self._inflow_summary()

    def _load_inflow_file(self):
        f, _ = self.W.QFileDialog.getOpenFileName(self.win, 'Inflow file', '', 'Flow files (*.flow *.txt *.csv *.dat)')
        if f:
            from ..io.inflow import read_inflow
            t, q = read_inflow(f)
            self._set_waveform(t, q)
            self.inflow_loaded_from = Path(f)
            self.inflow_info.setText('showing %s (%d samples, drawn with %d control points)'
                                     % (f, len(t), len(self.x_ctrl)))

    def save_inflow(self):
        from ..io.inflow import write_inflow
        if self.case is None:
            return self.error('create or open a case first')
        f = self._inflow_target()
        src = getattr(self, 'inflow_loaded_from', None)
        if not getattr(self, 'inflow_edited', False) and (f.exists() or src is not None):
            # nothing was drawn: keep the measured samples instead of the 20-knot approximation
            if src is not None and Path(src).resolve() != f.resolve():
                f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(str(src), str(f))
                self.inflow_info.setText('copied %s to %s (unchanged: the editor only draws it)' % (src, f))
            else:
                self.inflow_info.setText('%s is unchanged (drag a point to edit it)' % f)
            self._inflow_summary()
            self.refresh_status()
            return self.status('inflow unchanged')
        t, q = self.waveform()
        f.parent.mkdir(parents=True, exist_ok=True)
        write_inflow(t, q, f)
        self._inflow_summary()
        self.status('saved %s' % f)
        self.inflow_info.setText(self.inflow_info.text() + '<br>saved to %s' % f)
        self.refresh_status()

    # ------------------------------------------------------------ 3 targets
    def _build_bc_tab(self):
        W, QtCore = self.W, self.QtCore
        page = W.QWidget()
        lay = W.QVBoxLayout(page)
        lay.addWidget(W.QLabel('<b>Caps</b> — click one in the 3D view or in the table. Name them, pick the inlet, share the flow.'))
        self.table = W.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['name', 'area [cm²]', 'inlet', 'flow share [%]'])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.currentCellChanged.connect(lambda r, *_: self._select(r))
        lay.addWidget(self.table)
        row = W.QHBoxLayout()
        self.total = W.QLabel()
        row.addWidget(self.total); row.addStretch()
        eq = W.QPushButton('Equal split'); eq.clicked.connect(self._equal_split); row.addWidget(eq)
        ar = W.QPushButton('Split by area'); ar.setToolTip("share proportional to each outlet's cap area")
        ar.clicked.connect(self._area_split); row.addWidget(ar)
        lay.addLayout(row)
        lay.addWidget(W.QLabel('<b>Pressure target</b>'))
        grid = W.QFormLayout()
        self.anchor = W.QComboBox(); grid.addRow('measured at', self.anchor)
        self.sys = W.QDoubleSpinBox(); self.sys.setRange(1, 400); self.sys.setDecimals(0); self.sys.setValue(120)
        self.dia = W.QDoubleSpinBox(); self.dia.setRange(1, 400); self.dia.setDecimals(0); self.dia.setValue(80)
        grid.addRow('systolic [mmHg]', self.sys); grid.addRow('diastolic [mmHg]', self.dia)
        mr = W.QHBoxLayout()
        self.mean_on = W.QCheckBox('also target the mean')
        self.mean = W.QDoubleSpinBox(); self.mean.setRange(1, 400); self.mean.setDecimals(0); self.mean.setValue(93)
        self.mean.setEnabled(False); self.mean_on.toggled.connect(self.mean.setEnabled)
        mr.addWidget(self.mean_on); mr.addWidget(self.mean)
        grid.addRow('mean [mmHg]', mr)
        lay.addLayout(grid)
        hint = W.QLabel('The pulse pressure at the inlet has a floor set by the inflow waveform and the vessel inertia; '
                        'if a target is out of reach the tuner says so and keeps its best result.')
        hint.setWordWrap(True); hint.setStyleSheet('color: gray'); lay.addWidget(hint)
        self.bc_message = W.QLabel(''); self.bc_message.setWordWrap(True); lay.addWidget(self.bc_message)
        row2 = W.QHBoxLayout(); row2.addStretch()
        self.save_bc_btn = W.QPushButton('Save targets'); self.save_bc_btn.clicked.connect(self.save_bc)
        row2.addWidget(self.save_bc_btn)
        lay.addLayout(row2)
        self._next_button(lay)
        self.tabs.addTab(page, '3  Targets')
        self.name_edits, self.split_boxes, self.inlet_buttons = [], [], []
        self.inlet_group = None

    def _fill_bc_form(self):
        W = self.W
        bc = self.case.config.boundary_conditions
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.caps))
        self.name_edits, self.split_boxes, self.inlet_buttons = [], [], []
        self.inlet_group = W.QButtonGroup(self.table)
        for r, c in enumerate(self.caps):
            name = W.QLineEdit(self.names[r]); name.textEdited.connect(self._names_changed)
            self.name_edits.append(name); self.table.setCellWidget(r, 0, name)
            area = W.QTableWidgetItem('%.4f' % c.area); area.setFlags(self.QtCore.Qt.ItemIsEnabled)
            self.table.setItem(r, 1, area)
            radio = W.QRadioButton(); radio.setChecked(r == self.inlet_row); radio.toggled.connect(self._inlet_changed)
            self.inlet_group.addButton(radio, r); self.inlet_buttons.append(radio)
            holder = W.QWidget(); h = W.QHBoxLayout(holder); h.setContentsMargins(0, 0, 0, 0)
            h.addStretch(); h.addWidget(radio); h.addStretch()
            self.table.setCellWidget(r, 2, holder)
            box = W.QDoubleSpinBox(); box.setRange(0, 100); box.setDecimals(1)
            box.setValue(float(bc.flow_split.get(self.names[r], 0.0))); box.setEnabled(r != self.inlet_row)
            box.valueChanged.connect(self._splits_changed)
            self.split_boxes.append(box); self.table.setCellWidget(r, 3, box)
        self.table.blockSignals(False)
        p = bc.pressure_mmHg
        self.sys.setValue(p.systolic); self.dia.setValue(p.diastolic)
        self.mean_on.setChecked(p.mean is not None)
        if p.mean is not None:
            self.mean.setValue(p.mean)
        self._anchor_items(p.at)
        self._splits_changed()

    def _outlet_rows(self):
        return [r for r in range(len(self.caps)) if r != self.inlet_row]

    def _anchor_items(self, current, keep_index=None):
        items = ['inlet'] + [self.names[r] for r in self._outlet_rows()]
        self.anchor.blockSignals(True); self.anchor.clear(); self.anchor.addItems(items)
        if keep_index is not None and 0 <= keep_index < len(items):
            self.anchor.setCurrentIndex(keep_index)     # a rename keeps the same cap selected
        else:
            self.anchor.setCurrentIndex(items.index(current) if current in items else 0)
        self.anchor.blockSignals(False)

    def _select(self, row):
        if row is None or row < 0 or row >= len(self.caps):
            return
        self.selected = row
        self.viewer.highlight(self.caps, self.inlet_row, row)

    def _picked(self, mesh):
        if not self.caps:
            return
        c0 = np.asarray(mesh.center)
        row = int(np.argmin([np.linalg.norm(c.centroid - c0) for c in self.caps]))
        self.tabs.setCurrentIndex(self.TAB_TARGETS)
        self.table.setCurrentCell(row, 0)
        self._select(row)

    def _inlet_changed(self, *_):
        if self.inlet_group is None:
            return
        self.inlet_row = max(self.inlet_group.checkedId(), 0)
        for r, box in enumerate(self.split_boxes):
            box.setEnabled(r != self.inlet_row)
        self._anchor_items(self.anchor.currentText())
        self.viewer.labels(self.caps, self.names, self.inlet_row)
        self.viewer.highlight(self.caps, self.inlet_row, self.selected)
        self._splits_changed()

    def _names_changed(self, *_):
        keep = self.anchor.currentIndex()
        self.names = [e.text().strip() for e in self.name_edits]
        self._anchor_items(self.anchor.currentText(), keep_index=keep)
        self.viewer.labels(self.caps, self.names, self.inlet_row)
        if self.viewer.plotter is not None:
            self.viewer.plotter.render()

    def _splits_changed(self, *_):
        tot = sum(self.split_boxes[r].value() for r in self._outlet_rows()) if self.split_boxes else 0
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

    def bc_values(self):
        names = [e.text().strip() for e in self.name_edits]
        for n in names:
            if not _NAME_RE.match(n):
                raise ValueError("cap name %r: use letters, digits and underscores, starting with a letter" % n)
        if len(set(names)) != len(names):
            raise ValueError("cap names must be unique")
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
        return dict(inlet=names[self.inlet_row], cap_names=names, flow_split=split,
                    pressure=dict(at=self.anchor.currentText(), systolic=self.sys.value(),
                                  diastolic=self.dia.value(), mean=mean))

    def save_bc(self):
        from ..config_edit import update_case_yaml
        try:
            v = self.bc_values()
        except ValueError as e:
            self.bc_message.setText('<span style="color:#b3261e">%s</span>' % e)
            return
        update_case_yaml(self.case.yaml, **v)
        self.bc_message.setText('saved to %s' % self.case.yaml)
        self.status('targets saved')
        cur = self.tabs.currentIndex()
        self.load_case(self.case.dir)
        self.tabs.setCurrentIndex(cur)

    # ------------------------------------------------------------ 4 run
    def _build_run_tab(self):
        W = self.W
        page = W.QWidget()
        lay = W.QVBoxLayout(page)
        lay.addWidget(W.QLabel('<b>Run</b> — press Run. Only the stages whose inputs changed since the last run are '
                               'executed (the table shows which); the rest are reused.'))
        self.stage_table = W.QTableWidget(len(STAGES), 3)
        self.stage_table.setHorizontalHeaderLabels(['stage', 'state', 'detail'])
        self.stage_table.verticalHeader().setVisible(False)
        self.stage_table.horizontalHeader().setStretchLastSection(True)
        for i, s in enumerate(STAGES):
            self.stage_table.setItem(i, 0, W.QTableWidgetItem(s))
            self.stage_table.setItem(i, 1, W.QTableWidgetItem(''))
            self.stage_table.setItem(i, 2, W.QTableWidgetItem(''))
        lay.addWidget(self.stage_table)
        opts = W.QHBoxLayout()
        self.sim_0d_only = W.QRadioButton('0D simulation only')
        self.sim_0d_1d = W.QRadioButton('0D and 1D simulation'); self.sim_0d_1d.setChecked(True)
        grp = W.QButtonGroup(page); grp.addButton(self.sim_0d_only); grp.addButton(self.sim_0d_1d)
        self.sim_0d_1d.toggled.connect(self._sim_choice_changed)
        self.vol = W.QCheckBox('also project 1D results onto a 3D lumen mesh')
        self.vol.toggled.connect(lambda v: self._set_option('outputs.volume_projection', bool(v)))
        opts.addWidget(self.sim_0d_only); opts.addWidget(self.sim_0d_1d); opts.addSpacing(16); opts.addWidget(self.vol); opts.addStretch()
        lay.addLayout(opts)
        row = W.QHBoxLayout()
        self.run_btn = W.QPushButton('▶ Run'); self.run_btn.clicked.connect(lambda: self.start_run(None, False))
        self.run_btn.setToolTip('run the stages that are stale or have never run')
        self.force_btn = W.QPushButton('Re-run everything'); self.force_btn.clicked.connect(lambda: self.start_run(None, True))
        self.force_btn.setToolTip('ignore what was already computed and run every stage again')
        row.addWidget(self.run_btn); row.addWidget(self.force_btn); row.addStretch()
        lay.addLayout(row)
        self.log = W.QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setFont(self.QtGui.QFontDatabase.systemFont(self.QtGui.QFontDatabase.FixedFont))   # any OS
        self.log.setMaximumBlockCount(5000)
        lay.addWidget(self.log, 1)
        self.tabs.addTab(page, '4  Run')

    def _sim_choice_changed(self, one_d_checked):
        self.vol.setEnabled(bool(one_d_checked))
        self._set_option('simulation.run_1d', bool(one_d_checked))

    def _set_option(self, key, value):
        from ..config_edit import set_values
        if self.case is None:
            return
        set_values(self.case.yaml, {key: value})
        try:
            from ..case import Case
            self.case = Case(self.case.dir)
        except Exception as e:
            return self.error(str(e))
        self.refresh_status()

    def refresh_status(self):
        if self.case is None:
            return
        from ..case import Case
        try:
            self.case = Case(self.case.dir)
        except Exception as e:
            return self.error(str(e))
        s = self.case.config.simulation
        for b in (self.sim_0d_only, self.sim_0d_1d):
            b.blockSignals(True)
        (self.sim_0d_1d if s.run_1d else self.sim_0d_only).setChecked(True)
        for b in (self.sim_0d_only, self.sim_0d_1d):
            b.blockSignals(False)
        self.vol.blockSignals(True); self.vol.setChecked(bool(self.case.config.outputs.volume_projection)); self.vol.blockSignals(False)
        self.vol.setEnabled(bool(s.run_1d))
        for i, (name, state, detail) in enumerate(self.case.status()):
            self.stage_table.item(i, 1).setText(state)
            self.stage_table.item(i, 2).setText(str(detail)[:90])

    def _stage_event(self, stage, event):
        i = STAGES.index(stage)
        self.stage_table.item(i, 1).setText({'start': 'running…', 'done': 'done', 'fresh': 'fresh', 'skipped': 'skipped'}[event])

    def start_run(self, from_stage, force, until=None, on_done=None):
        if self.case is None:
            return self.error('create or open a case first')
        if self.worker is not None:
            return
        from qtpy import QtCore
        self.log.clear()
        self.run_btn.setEnabled(False)
        self.force_btn.setEnabled(False)
        self.tabs.setCurrentIndex(self.TAB_RUN)
        em = _RunEmitter.make()
        em.line.connect(self.log.appendPlainText)
        em.stage.connect(self._stage_event)
        em.done.connect(self._run_done)
        self._emitter = em
        self._on_run_done = on_done
        case_dir = self.case.dir

        class Worker(QtCore.QThread):
            def run(w):
                try:
                    run_case_blocking(case_dir, from_stage, force, em.line.emit, em.stage.emit, until=until)
                    em.done.emit(True, '')
                except Exception:
                    em.done.emit(False, traceback.format_exc())
        self.worker = Worker(self.win)          # parented to the window; released only once Qt says it finished
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _worker_finished(self):
        w = self.worker
        self.worker = None
        if w is not None:
            w.deleteLater()

    def _run_done(self, ok, err):
        # emitted from inside the thread: the QThread object must stay alive here (see _worker_finished)
        self.run_btn.setEnabled(True)
        self.force_btn.setEnabled(True)
        self.refresh_status()
        cb = getattr(self, '_on_run_done', None)
        self._on_run_done = None
        if not ok:
            self.log.appendPlainText(err)
            self.error('the run failed; see the log')
            if cb:
                cb(False)
            return
        if cb:
            cb(True)
            return
        self.status('run finished')
        self._fill_results()
        self.tabs.setCurrentIndex(self.TAB_RESULTS)

    # ------------------------------------------------------------ 5 results
    def _build_results_tab(self):
        W = self.W
        page = W.QWidget()
        lay = W.QVBoxLayout(page)
        lay.addWidget(W.QLabel('<b>Show in the 3D view</b>'))
        row = W.QHBoxLayout()
        self.q_pressure = W.QRadioButton('pressure'); self.q_pressure.setChecked(True)
        self.q_flow = W.QRadioButton('flow')
        self.on_wall = W.QRadioButton('on the wall'); self.on_wall.setChecked(True)
        self.on_cl = W.QRadioButton('on the centerline')
        g1 = W.QButtonGroup(page); g1.addButton(self.q_pressure); g1.addButton(self.q_flow)
        g2 = W.QButtonGroup(page); g2.addButton(self.on_wall); g2.addButton(self.on_cl)
        self.mean_box = W.QCheckBox('cycle mean')
        for wdg in (self.q_pressure, self.q_flow):
            row.addWidget(wdg)
        row.addSpacing(16)
        for wdg in (self.on_wall, self.on_cl):
            row.addWidget(wdg)
        row.addSpacing(16)
        row.addWidget(self.mean_box)
        row.addStretch()
        lay.addLayout(row)
        row2 = W.QHBoxLayout()
        self.show_1d_btn = W.QPushButton('Show 1D result'); self.show_1d_btn.clicked.connect(self._show_1d)
        capsb = W.QPushButton('Show caps'); capsb.clicked.connect(self._show_caps)
        openb = W.QPushButton('Open results folder'); openb.clicked.connect(self._open_results)
        row2.addWidget(self.show_1d_btn); row2.addWidget(capsb); row2.addStretch(); row2.addWidget(openb)
        lay.addLayout(row2)
        self.results_hint = W.QLabel('1D results are computed on the centerline; on the wall, every surface point '
                                     'shows the value of its nearest centerline point. The slider in the 3D view '
                                     'scrubs the last cardiac cycle.')
        self.results_hint.setWordWrap(True); self.results_hint.setStyleSheet('color: gray')
        lay.addWidget(self.results_hint)
        self.tune_info = W.QLabel(''); self.tune_info.setWordWrap(True); lay.addWidget(self.tune_info)
        self.res_table = W.QTableWidget(0, 5)
        self.res_table.setHorizontalHeaderLabels(['outlet', 'split %', 'sys', 'dia', 'mean [mmHg]'])
        self.res_table.verticalHeader().setVisible(False)
        self.res_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.res_table)
        self.plot_label = W.QLabel(''); self.plot_label.setAlignment(self.QtCore.Qt.AlignTop)
        scroll = W.QScrollArea(); scroll.setWidget(self.plot_label); scroll.setWidgetResizable(True)
        lay.addWidget(scroll, 1)
        self.tabs.addTab(page, '5  Results')

    def _show_caps(self):
        if self.surf is not None:
            self.viewer.show_model(self.surf, self.caps, self.names, self.inlet_row, self.selected, pick_callback=self._picked)
            self.status('caps')

    def _busy(self, on: bool):
        if self.offscreen:
            return
        from qtpy import QtCore, QtWidgets
        if on:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()
        QtWidgets.QApplication.processEvents()

    def _show_1d(self, *_):
        f = self.case.results_1d / 'extracted_results.vtp' if self.case else None
        if f is None or not f.exists():
            return self.error('No 1D results yet. Run with the 1D simulation enabled (Run step), then come back here.')
        quantity = 'pressure_mmHg' if self.q_pressure.isChecked() else 'flow'
        on = 'surface' if self.on_wall.isChecked() else 'centerline'
        self.status('loading 1D %s on the %s…' % (quantity.replace('_mmHg', ''), 'wall' if on == 'surface' else 'centerline'))
        self._busy(True)
        try:
            self.viewer.show_results(f, quantity, on=on, mean=self.mean_box.isChecked(), surf=self.surf)
            self.status('1D %s on the %s%s — drag the slider to scrub the cycle' % (
                quantity.replace('_mmHg', ''), 'wall' if on == 'surface' else 'centerline',
                ' (cycle mean)' if self.mean_box.isChecked() else ''))
        except Exception as e:
            self.error(str(e))
        finally:
            self._busy(False)

    def _open_results(self):
        if self.case is not None:
            from qtpy import QtGui, QtCore
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.case.results)))

    def _fill_results(self):
        if self.case is None:
            return
        rep = self.case.tuning_report
        if rep.exists():
            r = json.loads(rep.read_text())
            a = r.get('achieved', {}).get('pressure') or {}
            t = r.get('targets', {})
            txt = '<b>Tuning:</b> %s in %d solves — at %s achieved %.0f/%.0f (mean %.0f) vs target %g/%g' % (
                'converged' if r.get('converged') else 'stopped (%s)' % r.get('stop_reason', ''), r.get('solves', 0),
                t.get('at', ''), a.get('systolic', 0), a.get('diastolic', 0), a.get('mean', 0),
                t.get('systolic', 0), t.get('diastolic', 0))
            if r.get('note'):
                txt += '<br><span style="color:#9a6700">%s</span>' % r['note']
            self.tune_info.setText(txt)
        else:
            self.tune_info.setText('')
        stats = self.case.results_0d / '0D_statistics.csv'
        self.res_table.setRowCount(0)
        if stats.exists():
            import pandas as pd
            df = pd.read_csv(stats)
            self.res_table.setRowCount(len(df))
            for i, row in df.iterrows():
                for j, v in enumerate([row['outlet'], '%.1f' % row['flow_split_pct'], '%.1f' % row['systolic_mmHg'],
                                       '%.1f' % row['diastolic_mmHg'], '%.1f' % row['mean_pressure_mmHg']]):
                    self.res_table.setItem(i, j, self.W.QTableWidgetItem(str(v)))
        png = self.case.results_0d / '0D_outlets.png'
        if png.exists() and not self.offscreen:
            pix = self.QtGui.QPixmap(str(png))
            self.plot_label.setPixmap(pix.scaledToWidth(max(self.plot_label.width(), 500), self.QtCore.Qt.SmoothTransformation))
        else:
            self.plot_label.setText('')

    def show(self):
        self.win.show()


def run_app(case_dir=None, start_tab: int = MainWindow.TAB_MODEL) -> int:
    _require_qt()
    from qtpy import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    w = MainWindow(case_dir, start_tab=start_tab)
    w.show()
    return app.exec_() if hasattr(app, 'exec_') else app.exec()
