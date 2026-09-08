"""Stopping a real segmentation from the window, then watching a short one to the end.

    QT_QPA_PLATFORM=offscreen python tests/manual/smoke_stop.py

    MIROS_CASE     a case that has been segmented before (default ~/miros_cases/KDR12);
                   only its case.yaml is used, copied to a scratch case with the image path made absolute
    MIROS_STEPS    steps for the run that is left to finish (default 12)

Proves, on real data: the log pane fills while SeqSeg runs, the step counter
reaches the bar, Stop kills SeqSeg within seconds and leaves nothing behind,
the case resumes, and a run that finishes lands on the Outlets step.

While the worker runs, sys.stdout and sys.stderr are the window's log pane
(the worker redirects them process-wide), so this script talks through
sys.__stdout__. `kill -USR1 <pid>` writes every thread's stack to
stacks.txt in the scratch directory.
"""
import faulthandler
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(os.environ.get('MIROS_REPO', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
SRC = Path(os.environ.get('MIROS_CASE', Path.home() / 'miros_cases' / 'KDR12')).expanduser()
STEPS = int(os.environ.get('MIROS_STEPS', '12'))

from qtpy import QtWidgets
from miros.case import Case
from miros.config_edit import set_values
from miros.ui.app import MainWindow


def say(*a):
    print(*a, file=sys.__stdout__, flush=True)


src = Case(SRC)
root = Path(tempfile.mkdtemp(prefix='miros_stop_'))
d = root / 'case'
d.mkdir()
_stacks = open(root / 'stacks.txt', 'w')
faulthandler.register(signal.SIGUSR1, file=_stacks, all_threads=True)
say('scratch case:', d, ' pid:', os.getpid())
shutil.copy(SRC / 'case.yaml', d / 'case.yaml')
set_values(d / 'case.yaml', {'segmentation.image': str(src.resolve(src.config.segmentation.image)),
                             'segmentation.max_steps': 400})
if src.config.segmentation.config_name and '/' in src.config.segmentation.config_name:
    own = src.resolve(src.config.segmentation.config_name)
    (d / 'input').mkdir(exist_ok=True)
    shutil.copy(own, d / 'input' / own.name)
    set_values(d / 'case.yaml', {'segmentation.config_name': 'input/' + own.name})

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
w = MainWindow(d, offscreen=True)
w.error = lambda m: (_ for _ in ()).throw(AssertionError('GUI error dialog: ' + m))


def seqseg_pids():
    out = subprocess.run(['pgrep', '-f', '^\\S*python -u -m seqseg.seqseg run single'],
                         capture_output=True, text=True).stdout
    return [int(p) for p in out.split()]


def pump(until, limit):
    t0 = time.time()
    while not until() and time.time() - t0 < limit:
        app.processEvents(); time.sleep(0.05)
    return time.time() - t0


def main():
    # 1. start, watch the counter, stop
    assert not seqseg_pids(), 'a SeqSeg run is already going on this machine'
    w.segment.run_segment()
    assert w.worker is not None, 'no worker'
    assert w.stop_btn.isEnabled(), 'Stop not enabled'
    assert w.tabs.currentIndex() == w.TAB_RUN, 'not on the Run step: %d' % w.tabs.currentIndex()
    last = ''
    t0 = time.time()
    while time.time() - t0 < 300:
        app.processEvents(); time.sleep(0.05)
        if w.progress_text.text() != last:
            last = w.progress_text.text()
            say('%5.0f s  bar %d/%d  %r' % (time.time() - t0, w.progress_bar.value(), w.progress_bar.maximum(), last))
        if w.progress_bar.value() >= 3 and w.progress_bar.maximum() > 3:
            break
    assert w.progress_bar.value() >= 3, 'no step counter after %.0f s' % (time.time() - t0)
    assert 'step ' in w.progress_text.text() and 'branch' in w.progress_text.text()
    log = w.log.toPlainText()
    assert 'SeqSeg:' in log and 'Using config file' in log, log[-1500:]
    assert '%|' not in log, 'nnU-Net progress bars leaked into the log'
    assert '\x1b[' not in log
    pids = seqseg_pids()
    assert pids, 'no SeqSeg process found while the bar moves'
    say('SeqSeg pids while running:', pids)
    w.stop_run()
    took = pump(lambda: w.worker is None, 60)
    say('stopped in %.1f s' % took)
    assert w.worker is None, 'worker still running after Stop'
    assert took < 30
    assert not seqseg_pids(), 'SeqSeg survived the Stop: %s' % seqseg_pids()
    log = w.log.toPlainText()
    assert 'stop requested' in log and 'run stopped' in log and 'segment stopped after' in log, log[-1500:]
    assert w.run_btn.isEnabled() and not w.stop_btn.isEnabled() and w.progress_text.text() == 'stopped'
    assert dict((s, st) for s, st, _ in Case(d).status())['segment'] in ('never', 'stale')
    say('log tail after the stop:\n' + '\n'.join(log.splitlines()[-8:]))
    say('STOP OK')

    # 2. a short run left to finish. The Segment step saves its own settings when it runs, so
    #    they are set on the page, not in the YAML. SeqSeg's global centerline extraction on a
    #    short KDR12 trace grew to 23 GB and was OOM-killed, so the ends come from the surface here.
    w.segment.steps.setValue(STEPS)
    w.segment.centerline_box.setChecked(False)
    w.segment.run_segment()
    assert Case(d).config.segmentation.max_steps == STEPS
    took = pump(lambda: w.worker is None, 900)
    say('run of %d steps took %.0f s' % (STEPS, took))
    assert w.worker is None
    log = w.log.toPlainText()
    assert 'segment done' in log, log[-2000:]
    assert 'traced' in log and 'steps on' in log, log[-2000:]
    assert 'Total calculation time' in log, 'SeqSeg\'s closing lines were not streamed'
    assert 'vessel ends found on the surface' in log, log[-2000:]
    assert w.progress_text.text() == 'finished'
    assert w.tabs.currentIndex() == w.TAB_OUTLETS, w.tabs.currentIndex()
    assert w.outlets.planes, 'no vessel ends after the run'
    say('ends found:', [(p['name'], p.get('use', True)) for p in w.outlets.planes])
    say('the run log:\n' + '\n'.join(l for l in log.splitlines() if '  0%' not in l))
    say('FINISH OK')


try:
    main()
    ok = True
except BaseException as e:                      # noqa: BLE001 - report through the real stdout, then clean up
    import traceback
    say('FAILED:', ''.join(traceback.format_exception(type(e), e, e.__traceback__)))
    if w.log.toPlainText():
        say('log pane:\n' + w.log.toPlainText()[-3000:])
    ok = False
finally:
    if w.worker is not None:                    # never leave SeqSeg running
        w.stop_run()
        pump(lambda: w.worker is None, 60)
    for pid in seqseg_pids():
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass
    if ok:
        shutil.rmtree(root, ignore_errors=True)
    else:
        say('kept', root)
os._exit(0 if ok else 1)
