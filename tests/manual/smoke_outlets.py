"""The Outlets step: the cut list, editing a cut, applying it, choosing the inlet.

Run it with the MIROS environment and an offscreen Qt platform:

    QT_QPA_PLATFORM=offscreen python tests/manual/smoke_outlets.py

Paths come from the environment so the script survives a new machine:
    MIROS_REPO       the repo (default: two directories up from this file)
    MIROS_TUTORIAL   a SeqSeg tutorial case to work from (case.yaml + work/)
    MIROS_IMAGE      a CT or MR volume to load
"""
import os
import sys
import warnings
from pathlib import Path

REPO = Path(os.environ.get('MIROS_REPO', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
TUTORIAL = Path(os.environ.get('MIROS_TUTORIAL', REPO / 'examples' / 'seqseg_tutorial'))
IMAGE = Path(os.environ.get('MIROS_IMAGE', TUTORIAL / 'input' / '0110_0001.mha'))
import time, warnings
warnings.filterwarnings('ignore')
import json, numpy as np
from qtpy import QtWidgets
from miros.ui.app import MainWindow
from miros.config import load_config
CASE = TUTORIAL
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
w = MainWindow(CASE)
w.error = lambda m: (_ for _ in ()).throw(AssertionError('dialog: ' + m))
op = w.outlets
print('planes loaded:', len(op.planes), 'on:', sum(1 for p in op.planes if p.get('use', True)))
assert op.planes, 'the Outlets page found no ends'
assert op.surf is not None
assert w.tabs.isTabEnabled(w.TAB_OUTLETS)
names = [p['name'] for p in op.planes]
print('names:', names)
print('table rows:', op.table.rowCount(), '| count line:', op.count.text())
# untick one, retick, nudge, flip
from qtpy import QtCore
r = next(i for i, p in enumerate(op.planes) if not p.get('inlet'))
op.table.item(r, 0).setCheckState(QtCore.Qt.Unchecked)
assert op.planes[r]['use'] is False
op.table.item(r, 0).setCheckState(QtCore.Qt.Checked)
assert op.planes[r]['use'] is True
op.select(r)
before = list(op.planes[r]['origin'])
op.nudge(-0.5)
moved = np.linalg.norm(np.array(op.planes[r]['origin']) - np.array(before))
print('nudge moved the cut %.3f cm (expected %.3f)' % (moved, 0.5 * op.planes[r]['radius']))
assert abs(moved - 0.5 * op.planes[r]['radius']) < 1e-6
op.nudge(0.5)
n0 = list(op.planes[r]['normal']); op.flip_normal(); assert op.planes[r]['normal'] == [-v for v in n0]; op.flip_normal()
op.save()
cfg = load_config(CASE / 'case.yaml')
assert len(cfg.model.outlets) == len(op.planes), (len(cfg.model.outlets), len(op.planes))
print('saved to case.yaml:', len(cfg.model.outlets), 'planes;', sum(1 for p in cfg.model.outlets if p.get('use', True)), 'on')
# apply: runs preprocess in the worker
t0 = time.time()
op.apply()
while w.worker is not None and time.time() - t0 < 600:
    app.processEvents(); time.sleep(0.05)
assert w.worker is None
log = w.log.toPlainText()
assert 'preprocess done' in log, log[-600:]
print('applied in %.0f s; caps:' % (time.time() - t0), [(n, round(c.area, 3)) for n, c in zip(w.names, w.caps)])
assert w.tabs.currentIndex() == w.TAB_MODEL
print('OUTLETS PAGE OK')

# choosing the inlet in the table moves the flag and renames
from qtpy import QtCore as _Q
w.outlets.load_from_case()
op = w.outlets
r = next(i for i, p in enumerate(op.planes) if not p.get('inlet'))
op.table.item(r, 3).setCheckState(_Q.Qt.Checked)
assert sum(1 for p in op.planes if p.get('inlet')) == 1 and op.planes[r]['inlet']
assert op.planes[r]['name'] == 'inlet' and op.planes[r]['use'] is True
print('inlet moved to row %d: %s' % (r, op.planes[r]['name']))
print('INLET CHOICE OK')
