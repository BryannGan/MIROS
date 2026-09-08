"""The window on a surface case: caps, picking, 1D results, a run in the worker thread.

Run it with the MIROS environment and an offscreen Qt platform:

    QT_QPA_PLATFORM=offscreen python tests/manual/smoke_app3d.py

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
from qtpy import QtWidgets, QtCore
from miros.ui.app import MainWindow
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
import shutil, tempfile
ex = Path(tempfile.mkdtemp()) / 'aorta'
shutil.copytree(REPO / 'examples' / 'aorta', ex)   # work on a copy, never the tracked example
w0 = MainWindow()
assert not w0.model_next.isEnabled() and 'Create a case' in w0.model_next_hint.text()
w = MainWindow(ex)                                   # full window with the QtInteractor, existing results
assert w.model_next.isEnabled()
w.sim_0d_only.setChecked(True)
from miros.config import load_config
assert load_config(ex / 'case.yaml').simulation.run_1d is False and not w.vol.isEnabled()
w.sim_0d_1d.setChecked(True)
assert load_config(ex / 'case.yaml').simulation.run_1d is True and w.vol.isEnabled()
assert w.viewer.plotter is not None and len(w.viewer.actors) == 6, "caps not drawn"
w._picked(__import__('pyvista').wrap(w.caps[2].polydata)); assert w.table.currentRow() == 2
w.q_pressure.setChecked(True); w.on_wall.setChecked(True); w._show_1d(); assert w.viewer._results is not None, 'results not shown'
w.mean_box.setChecked(True); w._show_1d()
w.mean_box.setChecked(False); w.q_flow.setChecked(True); w.on_cl.setChecked(True); w._show_1d()
assert 'recommended' in w.rec_label.text().lower() and w.recommended and w.recommended >= 600, w.rec_label.text()
w._show_caps(); assert len(w.viewer.actors) == 6
assert w.res_table.rowCount() == 5, w.res_table.rowCount()
assert 'Tuning' in w.tune_info.text()
# background run through the real worker thread: everything is fresh, so it is a quick no-op
from miros.config_edit import set_values
set_values(ex / 'case.yaml', {'boundary_conditions.pressure_mmHg.systolic': 128.0, 'simulation.run_1d': False})
w.refresh_status()
w.start_run(None, False)
t0 = time.time()
while w.worker is not None and time.time() - t0 < 120:
    app.processEvents(); time.sleep(0.05)
assert w.worker is None, "worker did not finish"
assert w.run_btn.isEnabled() and 'tune done' in w.log.toPlainText() and 'extract_0d done' in w.log.toPlainText(), w.log.toPlainText()[-400:]
assert w.stage_table.item(3, 1).text() == 'fresh'
for _ in range(20): app.processEvents(); time.sleep(0.05)
assert w.worker is None
print("full app window OK: caps, picking, 1D results view, worker run")
# regression: saving targets re-renders and must not trip "picking already enabled"
w.tabs.setCurrentIndex(w.TAB_TARGETS); w._equal_split(); w.save_bc(); assert 'saved' in w.bc_message.text(), w.bc_message.text()
w.save_bc(); assert 'saved' in w.bc_message.text()
# the log must be plain text
assert '\x1b[' not in w.log.toPlainText(), "ANSI codes in the log"
print("save-twice and plain log OK")
