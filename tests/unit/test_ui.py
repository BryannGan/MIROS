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
    assert win.stage_table.item(0, 1).text() == 'fresh'
