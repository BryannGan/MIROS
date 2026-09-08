"""The Segment step end to end: image, seeds by clicking, SeqSeg, the ends it finds.

Run it with the MIROS environment and an offscreen Qt platform:

    QT_QPA_PLATFORM=offscreen python tests/manual/smoke_segment.py

Paths come from the environment so the script survives a new machine:
    MIROS_REPO       the repo (default: two directories up from this file)
    MIROS_TUTORIAL   a SeqSeg tutorial case to work from (case.yaml + work/)
    MIROS_IMAGE      a CT or MR volume to load
"""
import os
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get('MIROS_REPO', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
TUTORIAL = Path(os.environ.get('MIROS_TUTORIAL', REPO / 'examples' / 'seqseg_tutorial'))
IMAGE = Path(os.environ.get('MIROS_IMAGE', TUTORIAL / 'input' / '0110_0001.mha'))
from qtpy import QtWidgets
from miros.ui.app import MainWindow
from miros.config import load_config
from miros.config_edit import set_values
S = TUTORIAL
img = IMAGE
ref = load_config(S / 'case_seqseg' / 'case.yaml').segmentation
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
w = MainWindow()
w.error = lambda m: (_ for _ in ()).throw(AssertionError('GUI error dialog: ' + m))
assert w.tabs.currentIndex() == w.TAB_MODEL and w.tabs.count() == 6
sp = w.segment
sp.load_image(img)
print('units guessed:', sp.units.currentText(), sp.units_hint.text())
assert w.viewer._image is not None
sp.units.setCurrentText(ref.units)
i = sp.model.findData(ref.model); sp.model.setCurrentIndex(i); assert sp.model_status.text() == 'ready', sp.model_status.text()
d = Path(tempfile.mkdtemp()) / 'gui_seg'
sp.image_edit.setText(str(img)); sp.case_edit.setText(str(d))
sp.create_case()
assert w.case is not None and (d / 'case.yaml').exists()
assert not w.tabs.isTabEnabled(w.TAB_INFLOW) and w.tabs.isTabEnabled(w.TAB_RUN) and not w.model_next.isEnabled()
# seeds by two clicks each, as in the GUI
sp.pick_btn.setChecked(True)
for s in ref.seeds:
    sp.radius.setValue(s.radius)
    sp._picked_point(s.point); assert sp.pending is not None
    sp._picked_point(s.direction); assert sp.pending is None
sp.pick_btn.setChecked(False)
assert len(sp.seeds) == len(ref.seeds) and sp.seed_table.rowCount() == len(ref.seeds)
sp._remove_seed(0); sp._picked_point(ref.seeds[0].point); sp._picked_point(ref.seeds[0].direction)
sp.save_seeds()
cfg = load_config(d / 'case.yaml')
assert len(cfg.segmentation.seeds) == len(ref.seeds) and cfg.segmentation.model == ref.model and cfg.segmentation.units == ref.units
print('seeds saved:', [(s.point, s.radius) for s in cfg.segmentation.seeds])
set_values(d / 'case.yaml', {'segmentation.max_steps': ref.max_steps})   # config_name left empty: the model picks it
w.refresh_status()
# reopen: the page must be filled from the case
w2 = MainWindow(d)
assert w2.segment.seed_table.rowCount() == len(ref.seeds) and w2.tabs.isTabEnabled(w2.TAB_RUN) and not w2.tabs.isTabEnabled(w2.TAB_INFLOW)
print('reopen OK')
# the real run through the worker: segment -> preprocess, then the window lands on the Model tab with caps
t0 = time.time()
sp.run_segment()
assert w.worker is not None
while w.worker is not None and time.time() - t0 < 900:
    app.processEvents(); time.sleep(0.05)
assert w.worker is None, 'worker did not finish'
print('run took %.0f s' % (time.time() - t0))
log = w.log.toPlainText()
assert 'preprocess done' in log, log[-800:]
assert w.tabs.currentIndex() == w.TAB_MODEL and w.tabs.isTabEnabled(w.TAB_INFLOW), w.tabs.currentIndex()
assert w.caps and len(w.viewer.actors) == len(w.caps), (len(w.caps), len(w.viewer.actors))
print('caps after segmentation:', [(n, round(c.area, 3)) for n, c in zip(w.names, w.caps)])
assert '\x1b[' not in log
for _ in range(20): app.processEvents(); time.sleep(0.05)
print('SEGMENT PAGE OK')
