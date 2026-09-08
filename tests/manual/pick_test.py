"""Seed picking driven by real Qt mouse events: a click places a point, a drag does not.

Run it with the MIROS environment and an offscreen Qt platform:

    QT_QPA_PLATFORM=offscreen python tests/manual/pick_test.py

Paths come from the environment so the script survives a new machine:
    MIROS_REPO       the repo (default: two directories up from this file)
    MIROS_TUTORIAL   a SeqSeg tutorial case to work from (case.yaml + work/)
    MIROS_IMAGE      a CT or MR volume to load
"""
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get('MIROS_REPO', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
TUTORIAL = Path(os.environ.get('MIROS_TUTORIAL', REPO / 'examples' / 'seqseg_tutorial'))
IMAGE = Path(os.environ.get('MIROS_IMAGE', TUTORIAL / 'input' / '0110_0001.mha'))
import numpy as np
from qtpy import QtWidgets
from miros.ui.app import MainWindow
S = TUTORIAL
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
w = MainWindow()
w.error = lambda m: (_ for _ in ()).throw(AssertionError('dialog: ' + m))
sp = w.segment
sp.load_image(IMAGE)
print('can_pick:', w.viewer.can_pick)
w.win.resize(1600, 900); w.win.show(); app.processEvents()
w.viewer.widget.resize(900, 700); app.processEvents()
w.viewer.plotter.render_window.SetSize(900, 700); w.viewer.plotter.render(); app.processEvents()
got = []
w.viewer.enable_slice_picking(lambda p: got.append(np.asarray(p, float)))
from qtpy import QtCore, QtGui
widget = w.viewer.widget
cx, cy = widget.width() // 2, widget.height() // 2
print('widget size', widget.width(), widget.height(), 'render window', w.viewer.plotter.render_window.GetSize())

def click(x, y, drag=0):
    # a real Qt mouse click on the render widget, exactly as the user's mouse delivers it
    for kind, pos in ((QtCore.QEvent.MouseButtonPress, (x, y)),
                      (QtCore.QEvent.MouseButtonRelease, (x + drag, y))):
        ev = QtGui.QMouseEvent(kind, QtCore.QPointF(*pos), QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                               QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(widget, ev)

click(cx, cy)
print('click on the slices ->', got[-1] if got else 'nothing picked')
n_after_click = len(got)
click(cx, cy, drag=40)          # a rotation must not place a seed
print('drag added a point:', len(got) > n_after_click)
assert len(got) == n_after_click, 'a drag placed a seed'
assert n_after_click == 1, 'the click did not pick a point on a slice'
# the picked point must lie inside the volume
b = sp.image.bounds
p = got[0]
assert all(b[2*i] - 1e-6 <= p[i] <= b[2*i+1] + 1e-6 for i in range(3)), (p, b)
# two clicks make one seed, and picking survives being switched off and on
sp.pick_btn.setChecked(True)
click(cx, cy); click(cx + 30, cy + 30)
print('seeds after two clicks:', len(sp.seeds), sp.seeds)
assert len(sp.seeds) == 1
sp.pick_btn.setChecked(False)
click(cx, cy)
assert len(sp.seeds) == 1, 'clicks still land after the button is off'
sp.pick_btn.setChecked(True)
click(cx - 20, cy); click(cx - 40, cy)
assert len(sp.seeds) == 2, sp.seeds
print('PICKING OK', sp.seeds[-1])
