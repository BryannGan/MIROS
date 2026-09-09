import gc
import os

import numpy as np
import pytest
import yaml

from miros.config import load_config, write_template
from miros.config_edit import update_case_yaml


def test_update_case_yaml_keeps_comments_and_values(tmp_path):
    p = tmp_path / 'case.yaml'
    write_template(p, outlet_names=['cap_2', 'cap_3'], inlet='cap_1')
    update_case_yaml(p, inlet='cap_2', cap_names=['root', 'desc', 'lcca'],
                     flow_split={'root': 70, 'lcca': 30},
                     pressure={'at': 'root', 'systolic': 125, 'diastolic': 78, 'mean': None})
    text = p.read_text()
    assert '# MIROS case file' in text and 'tolerance_pct' in text          # comments and untouched keys survive
    cfg = load_config(p)
    assert cfg.model.inlet == 'cap_2' and cfg.model.cap_names == ['root', 'desc', 'lcca']
    assert cfg.boundary_conditions.flow_split == {'root': 70.0, 'lcca': 30.0}
    assert cfg.boundary_conditions.pressure_mmHg.at == 'root' and cfg.boundary_conditions.pressure_mmHg.mean is None


def test_draggable_points_respond_to_pick_and_motion():
    """The editor's control points must move on drag (regression: the handler object was garbage-collected)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backend_bases import MouseEvent
    from miros.ui.waveform_editor import _DraggablePoints

    fig, ax = plt.subplots()
    x = np.linspace(0, 1, 5)
    y = np.zeros(5)
    ax.set_xlim(0, 1); ax.set_ylim(-1, 1)
    moved = []
    dragger = _DraggablePoints(ax, x, y, lambda: moved.append(1))
    gc.collect()
    fig.canvas.draw()
    px, py = ax.transData.transform((x[2], y[2]))
    press = MouseEvent('button_press_event', fig.canvas, px, py, button=1)
    fig.pick(press)                                          # fires pick_event on the scatter
    assert dragger._ind == 2
    px2, py2 = ax.transData.transform((x[2], 0.5))
    fig.canvas.callbacks.process('motion_notify_event', MouseEvent('motion_notify_event', fig.canvas, px2, py2, button=1))
    assert abs(y[2] - 0.5) < 1e-6 and moved
    fig.canvas.callbacks.process('button_release_event', MouseEvent('button_release_event', fig.canvas, px2, py2, button=1))
    assert dragger._ind is None
    plt.close(fig)


@pytest.fixture
def qt_app():
    pytest.importorskip('qtpy')
    pytest.importorskip('pyvistaqt')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from qtpy import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.slow
def test_app_create_case_targets_and_inflow(surface_path, tmp_path, qt_app):
    """The window (without the 3D view) creates a case from a surface, saves targets and an inflow."""
    from miros.ui.app import MainWindow

    w = MainWindow(offscreen=True)
    w.surface_edit.setText(str(surface_path))
    w.case_edit.setText(str(tmp_path / 'c'))
    w.units.setCurrentText('cm')
    w.create_case()
    assert w.case is not None and len(w.caps) == 6 and (tmp_path / 'c' / 'case.yaml').exists()

    # targets
    w.name_edits[0].setText('root'); w._names_changed()
    w.inlet_buttons[1].setChecked(True)                      # second-largest cap becomes the inlet
    w._equal_split()
    assert 'must be 100' not in w.total.text()
    w.anchor.setCurrentText('inlet')
    w.sys.setValue(125); w.dia.setValue(78)
    w.save_bc()
    assert 'saved' in w.bc_message.text(), w.bc_message.text()
    cfg = load_config(tmp_path / 'c' / 'case.yaml')
    assert cfg.model.inlet == 'cap_2' and cfg.model.cap_names[0] == 'root'
    assert 'cap_2' not in cfg.boundary_conditions.flow_split and 'root' in cfg.boundary_conditions.flow_split
    assert abs(sum(cfg.boundary_conditions.flow_split.values()) - 100) < 0.1
    assert cfg.boundary_conditions.pressure_mmHg.systolic == 125
    w.split_boxes[0].setValue(5)
    w.save_bc()
    assert 'must sum to 100' in w.bc_message.text()

    # inflow from the embedded editor
    w.hr.setValue(75); w.npts.setValue(600)
    w.y_ctrl[:] = 100 * np.sin(np.pi * w.x_ctrl) ** 2
    w.save_inflow()
    f = tmp_path / 'c' / 'input' / 'inflow.flow'
    assert f.exists()
    t = np.loadtxt(f)
    assert t.shape == (600, 2) and abs(t[-1, 0] - 0.8) < 1e-6
    states = dict((s, st) for s, st, _ in w.case.status())
    assert states['preprocess'] == 'never'


@pytest.mark.slow
def test_app_runs_preprocess_in_worker(surface_path, tmp_path, qt_app):
    from miros.ui.app import MainWindow, run_case_blocking
    from miros.cli import main
    d = tmp_path / 'c'
    assert main(['init', str(d), '--surface', str(surface_path)]) == 0
    lines, events = [], []
    from miros.case import Case
    # the worker body, synchronously, limited to the first stage
    import contextlib
    from miros.ui.app import _LineWriter
    w = _LineWriter(lines.append)
    with contextlib.redirect_stdout(w):
        Case(d).run(until='preprocess', progress=lambda s, e: events.append((s, e)))
    w.flush()
    assert ('preprocess', 'start') in events and ('preprocess', 'done') in events
    assert any('preprocess' in l for l in lines)
    win = MainWindow(d, offscreen=True)
    win.refresh_status()
    from miros.config import STAGES
    assert win.stage_table.item(STAGES.index('preprocess'), 1).text() == 'fresh'
    assert win.stage_table.item(STAGES.index('segment'), 1).text() == 'disabled'


@pytest.mark.slow
def test_seed_picking_places_points_on_a_click_but_not_on_a_drag(qt_app, tmp_path):
    """A click on a slice places a seed point; a drag turns the view instead (Segment step)."""
    import pyvista as pv
    from qtpy import QtCore, QtGui, QtWidgets
    from miros.ui.app import MainWindow

    import sys
    if qt_app.platformName() == 'offscreen' and not (sys.platform.startswith('linux') and os.environ.get('DISPLAY')):
        # VTK makes its own GL context for the 3D view; without a display server (Linux) or a real
        # platform (macOS, Windows) a mouse press on the interactor is a segfault, not a skip
        pytest.skip('the 3D view needs a display')
    w = MainWindow()                                  # with the 3D view: picking needs the render widget
    if not w.viewer.can_pick:
        pytest.skip('no render widget in this environment')
    grid = pv.ImageData(dimensions=(20, 20, 20), spacing=(0.5, 0.5, 0.5), origin=(0.0, 0.0, 0.0))
    grid.point_data['intensity'] = np.linspace(0, 1, grid.n_points, dtype=np.float32)
    w.viewer.show_image(grid)
    w.win.resize(1200, 800); w.win.show(); qt_app.processEvents()
    w.viewer.widget.resize(600, 500); qt_app.processEvents()
    w.viewer.plotter.render_window.SetSize(600, 500); w.viewer.plotter.render(); qt_app.processEvents()

    picked = []
    w.viewer.enable_slice_picking(picked.append)
    widget = w.viewer.widget
    cx, cy = widget.width() // 2, widget.height() // 2

    def click(x, y, drag=0):
        for kind, pos in ((QtCore.QEvent.MouseButtonPress, (x, y)),
                          (QtCore.QEvent.MouseButtonRelease, (x + drag, y))):
            QtWidgets.QApplication.sendEvent(widget, QtGui.QMouseEvent(
                kind, QtCore.QPointF(*pos), QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))

    click(cx, cy)
    assert len(picked) == 1, 'a click on the slices picked nothing'
    b = grid.bounds
    assert all(b[2 * i] - 1e-6 <= picked[0][i] <= b[2 * i + 1] + 1e-6 for i in range(3))
    click(cx, cy, drag=40)
    assert len(picked) == 1, 'turning the view placed a point'
    w.viewer.disable_pick()
    click(cx, cy)
    assert len(picked) == 1, 'clicks still picked after picking was switched off'


@pytest.mark.slow
def test_segment_page_loads_a_typed_image_path(qt_app, tmp_path):
    """A path typed or pasted into the image box loads the volume (not only the Browse button)."""
    import pyvista as pv
    from miros.ui.app import MainWindow

    grid = pv.ImageData(dimensions=(12, 12, 12), spacing=(0.1, 0.1, 0.1))
    grid.point_data['scan'] = np.arange(grid.n_points, dtype=np.int16)
    f = tmp_path / 'scan.vti'
    grid.save(str(f))
    w = MainWindow(offscreen=True)                    # the page, not the 3D view
    errors = []
    w.error = errors.append
    w.segment.image_edit.setText(str(f))
    w.segment._image_path_typed()
    assert not errors and w.segment.image is not None
    assert w.segment.image.dimensions == (12, 12, 12)
    assert w.segment.image.point_data['intensity'].dtype == np.int16   # no float32 copy of a big scan
    w.segment.image_edit.setText(str(tmp_path / 'missing.vti'))
    w.segment._image_path_typed()
    assert errors and 'no such file' in errors[-1]


def test_window_fits_a_laptop_screen(qt_app):
    """No page may set a minimum width beyond a laptop screen (a label that cannot wrap did: 1737 px)."""
    from qtpy import QtWidgets
    from miros.ui.app import MainWindow
    w = MainWindow(offscreen=True)
    w.win.show(); qt_app.processEvents()

    def widest(widget, n=5):                                   # what sets a page's minimum, for the message
        rows = []
        for c in widget.findChildren(QtWidgets.QWidget):
            text = c.text()[:50] if hasattr(c, 'text') and isinstance(c.text(), str) else ''
            rows.append((c.minimumSizeHint().width(), type(c).__name__, text))
        return sorted(rows, reverse=True)[:n]
    pages = {w.tabs.tabText(i): w.tabs.widget(i) for i in range(w.tabs.count())}
    report = '; '.join('%s %d' % (name, p.minimumSizeHint().width()) for name, p in pages.items())
    big = max(pages.values(), key=lambda p: p.minimumSizeHint().width())
    report += ' | widest widgets: %s' % widest(big)
    # in characters of the platform's font, so a wide font (Windows offscreen: 12 px a character) is not a failure;
    # the label that could not wrap was 250 characters, a 1366-px laptop at 7 px a character is about 195
    from qtpy import QtGui
    fm = QtGui.QFontMetrics(qt_app.font())
    cw, lh = fm.horizontalAdvance('x' * 100) / 100.0, fm.lineSpacing()
    hint = w.win.minimumSizeHint()
    assert hint.width() < 140 * cw and hint.height() < 45 * lh, ((hint.width(), hint.height()), (cw, lh), report)
    for name, p in pages.items():
        assert p.minimumSizeHint().width() < 140 * cw, (name, (cw, lh), report)
    # opened no larger than the screen, unless the minimum itself is larger (a tiny offscreen screen)
    avail = qt_app.primaryScreen().availableGeometry()
    assert w.win.width() <= max(avail.width(), hint.width()), (w.win.width(), avail.width(), report)
    assert w.win.height() <= max(avail.height(), hint.height()), (w.win.height(), avail.height(), report)


def test_stop_button_ends_the_run_and_shows_progress(surface_path, tmp_path, qt_app, monkeypatch):
    """Progress reported by a stage reaches the bar; Stop ends the worker, which is released cleanly."""
    import threading
    import time
    from miros.cli import main
    from miros.case import RunCancelled
    from miros.ui import app as A
    d = tmp_path / 'c'
    assert main(['init', str(d), '--surface', str(surface_path)]) == 0

    def fake_run(case_dir, from_stage, force, emit_line, emit_stage, until=None, only=None,
                 cancel=None, emit_progress=None):
        assert isinstance(cancel, threading.Event)
        emit_stage('preprocess', 'start')
        emit_line('working')
        for i in range(1, 201):
            emit_progress(i, 200, 'step %d of 200' % i)
            if cancel.wait(0.02):
                raise RunCancelled('stopped at step %d' % i)
        emit_stage('preprocess', 'done')
    monkeypatch.setattr(A, 'run_case_blocking', fake_run)

    w = A.MainWindow(d, offscreen=True)
    w.win.show()
    outcome = []
    w.start_run(None, False, on_done=outcome.append)
    assert w.worker is not None and not w.run_btn.isEnabled() and w.stop_btn.isEnabled()
    t0 = time.time()
    while w.progress_bar.value() < 3 and time.time() - t0 < 10:
        qt_app.processEvents(); time.sleep(0.01)
    assert w.progress_bar.value() >= 3 and w.progress_bar.maximum() == 200
    assert w.progress_text.text().startswith('step ') and w.tabs.currentIndex() == w.TAB_RUN
    from miros.config import STAGES
    assert w.stage_table.item(STAGES.index('preprocess'), 1).text() == 'running…'
    w.stop_run()
    assert not w.stop_btn.isEnabled()
    while w.worker is not None and time.time() - t0 < 15:
        qt_app.processEvents(); time.sleep(0.01)
    assert w.worker is None, 'the worker did not finish after Stop'
    assert outcome == ['stopped']
    assert w.run_btn.isEnabled() and w.force_btn.isEnabled() and not w.stop_btn.isEnabled()
    assert w.progress_text.text() == 'stopped' and w.progress_bar.maximum() == 1
    log = w.log.toPlainText()
    assert 'stop requested' in log and 'run stopped (stopped at step' in log
    assert w.case.status()[1][1] == 'never'                  # nothing was recorded for the stopped stage
    w.start_run(None, False, on_done=outcome.append)          # and a new run can start
    assert w.worker is not None
    w.stop_run()
    while w.worker is not None and time.time() - t0 < 25:
        qt_app.processEvents(); time.sleep(0.01)
    assert outcome == ['stopped', 'stopped']
