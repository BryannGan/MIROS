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


@pytest.mark.slow
def test_setup_window_form_saves_case(surface_path, tmp_path):
    pytest.importorskip('qtpy')
    pytest.importorskip('pyvistaqt')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from qtpy import QtWidgets
    from miros.cli import main
    from miros.ui.setup_window import SetupWindow

    d = tmp_path / 'c'
    assert main(['init', str(d), '--surface', str(surface_path)]) == 0
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = SetupWindow(d, offscreen=True)
    assert len(w.caps) == 6
    w.name_edits[0].setText('root'); w._names_changed()
    w._equal_split()
    assert 'must be 100' not in w.total.text()
    w.inlet_buttons[1].setChecked(True)                      # second-largest cap becomes the inlet
    w._equal_split()
    w.anchor.setCurrentText('inlet')
    w.sys.setValue(125); w.dia.setValue(78)
    w.save()
    assert 'saved' in w.message.text()
    cfg = load_config(d / 'case.yaml')
    assert cfg.model.inlet == 'cap_2' and cfg.model.cap_names[0] == 'root'
    assert 'cap_2' not in cfg.boundary_conditions.flow_split and 'root' in cfg.boundary_conditions.flow_split
    assert abs(sum(cfg.boundary_conditions.flow_split.values()) - 100) < 0.1
    assert cfg.boundary_conditions.pressure_mmHg.systolic == 125
    # invalid state is refused
    w.split_boxes[0].setValue(5)
    w.save()
    assert 'must sum to 100' in w.message.text()
