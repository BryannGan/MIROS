"""The subprocess runner, the progress channel, SeqSeg's step counter, and stopping a run."""
import os
import sys
import threading
import time

import pytest

from miros.io.process import RunCancelled, kill_tree, run_logged, strip_ansi
from miros.ui import console


def test_run_logged_streams_every_line_and_keeps_the_log(tmp_path):
    """stdout and stderr both arrive line by line while the program runs, and the log has it all."""
    code = ('import sys, time\n'
            'for i in range(3):\n'
            '    print("out", i, flush=True); print("err", i, file=sys.stderr, flush=True); time.sleep(0.05)\n'
            'sys.stdout.write("a\\rb\\n"); sys.stdout.flush()\n')
    seen = []
    log = tmp_path / 'p.log'
    code_rc = run_logged([sys.executable, '-c', code], log, on_line=lambda s: seen.append((s, time.time())),
                         poll_interval=0.05)
    assert code_rc == 0
    lines = [s for s, _ in seen]
    assert 'out 0' in lines and 'err 2' in lines and lines[-2:] == ['a', 'b']   # \r splits a line like \n does
    assert seen[-1][1] - seen[0][1] > 0.08, 'lines were delivered in one batch at the end, not as printed'
    assert log.read_text().count('out ') == 3 and 'err 1' in log.read_text()


def test_run_logged_polls_while_running_and_returns_the_exit_code(tmp_path):
    polls = []
    rc = run_logged([sys.executable, '-c', 'import time, sys; time.sleep(0.3); sys.exit(3)'], tmp_path / 'p.log',
                    poll=lambda: polls.append(time.time()), poll_interval=0.05)
    assert rc == 3 and len(polls) >= 3


def test_stop_kills_the_program_and_its_children(tmp_path):
    """Setting the event ends the run within the grace period, and the process tree is gone."""
    pidfile = tmp_path / 'pid'
    code = ('import os, subprocess, sys, time\n'
            'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
            'open(%r, "w").write("%%d %%d" %% (os.getpid(), child.pid))\n'
            'print("started", flush=True)\n'
            'time.sleep(60)\n') % str(pidfile)
    ev = threading.Event()
    t0 = time.time()
    with pytest.raises(RunCancelled):
        run_logged([sys.executable, '-c', code], tmp_path / 'p.log',
                   on_line=lambda s: ev.set() if s == 'started' else None, cancel=ev, poll_interval=0.05)
    assert time.time() - t0 < 15
    if os.name != 'nt':
        pids = [int(p) for p in pidfile.read_text().split()]
        time.sleep(0.2)
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive = True
                # a zombie answers kill(0): make sure it is not merely unreaped
                alive = 'zombie' not in open('/proc/%d/status' % pid).read().lower() if os.path.exists('/proc') else alive
            except ProcessLookupError:
                alive = False
            assert not alive, 'process %d survived the stop' % pid


def test_kill_tree_on_a_finished_process_is_harmless(tmp_path):
    import subprocess
    p = subprocess.Popen([sys.executable, '-c', 'pass'])
    p.wait()
    kill_tree(p)


def test_console_progress_goes_to_the_handler_or_prints_by_tenths(capsys):
    got = []
    console.set_progress_handler(lambda d, t, s: got.append((d, t, s)))
    try:
        console.progress(3, 10, 'step 3')
        console.progress(None)
    finally:
        console.set_progress_handler(None)
    assert got == [(3, 10, 'step 3'), (None, None, '')]
    for i in range(1, 101):                      # piped output: a line per tenth, not per step
        console.progress(i, 100, 'step %d of 100' % i)
    console.progress(None)
    out = capsys.readouterr().out.splitlines()
    assert 9 <= len(out) <= 11 and out[-1].strip() == 'step 100 of 100', out
    console.info('after')                        # and a report never swallows the next message
    assert capsys.readouterr().out.strip() == 'after'


def test_seqseg_log_lines_keep_words_and_drop_bars():
    from miros.stages.segment import _log_line
    shown = []
    console.set_progress_handler(None)
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _log_line('  0%|          | 0/1 [00:00<?, ?it/s]')
        _log_line('100%|██████████| 1/1 [00:00<00:00, 93.43it/s]')
        _log_line('')
        _log_line('\x1b[0m\x1b[33m2026-09-03 17:57:46 vtkWindowedSincPolyData WARN| No data to smooth!\x1b[0m')
        _log_line('Using config file: global_aorta')
    shown = buf.getvalue().splitlines()
    assert shown == ['  2026-09-03 17:57:46 vtkWindowedSincPolyData WARN| No data to smooth!',
                     '  Using config file: global_aorta']
    assert strip_ansi('\x1b[31mred\x1b[0m') == 'red'


def test_seqseg_step_counter_is_read_from_its_out_txt(tmp_path):
    """The counter lives in out.txt in SeqSeg's scratch directory and is reported as it grows."""
    from miros.stages.segment import _Tracing
    scratch = tmp_path / 'seqseg3d_fullres_case'
    scratch.mkdir()
    out = scratch / 'out.txt'
    got = []
    console.set_progress_handler(lambda d, t, s: got.append((d, t, s)))
    try:
        tr = _Tracing(tmp_path, max_steps=80)
        tr.poll()                                            # nothing yet: SeqSeg is still loading the model
        assert got == [] and tr.step == -1
        out.write_text('Done loading model\n\n*** Step number 0 ***\n2026-09-03 17:57:40\nKeeping original size\n'
                       '\n*** Step number 1 ***\n\n*** Step number 2 ***\n')
        tr.poll()
        assert got[-1][:2] == (3, 80) and got[-1][2].startswith('step 3 of up to 80, branch 1')
        tr.poll()                                            # no new text: no new report
        assert len(got) == 1
        with open(out, 'a') as f:                            # a retry repeats a number; a branch change is counted
            f.write('*** Step number 2 ***\nError for step\nPost Branches are: \n*** Step number 3 ***\n')
        tr.poll()
        assert got[-1][:2] == (4, 80) and 'branch 2' in got[-1][2] and len(got) == 2
    finally:
        console.set_progress_handler(None)


def test_case_run_stops_before_the_next_stage(surface_path, tmp_path):
    from miros.case import Case, RunCancelled
    from miros.cli import main
    d = tmp_path / 'c'
    assert main(['init', str(d), '--surface', str(surface_path)]) == 0
    ev = threading.Event()
    ev.set()
    events = []
    with pytest.raises(RunCancelled, match='before preprocess'):
        Case(d).run(until='preprocess', cancel=ev, progress=lambda s, e: events.append((s, e)))
    assert ('preprocess', 'start') not in events
    assert dict((s, st) for s, st, _ in Case(d).status())['preprocess'] == 'never'   # nothing recorded


def test_windkessel_check_runs_before_a_solve_is_spent(monkeypatch):
    """The tuner asks `check` at the top of each iteration, so Stop is honoured before the next 0D solve."""
    from miros.tuning import windkessel as W
    calls, solves = [], []

    def check():
        calls.append(1)
        raise RunCancelled('stopped')
    monkeypatch.setattr(W, 'analytic_initial_state', lambda *a, **k: ({'o': 1.0}, 0.1, 1e-4))
    monkeypatch.setattr(W, 'build_rcr', lambda *a, **k: {'o': {'Rp': 1, 'C': 1, 'Rd': 1}})
    monkeypatch.setattr(W, '_measure', lambda *a, **k: solves.append(1) or ({'o': 1.0}, {}))
    monkeypatch.setattr(W.Z, 'VesselMap', lambda cfg, names: type('M', (), {'outlet_names': list(names)})())
    import numpy as np
    t = np.linspace(0, 1, 10); q = np.ones(10)
    targets = W.Targets(flow_split={'o': 1.0}, at='inlet', systolic=120, diastolic=80, mean=None)
    with pytest.raises(RunCancelled):
        W.tune({}, ['o'], targets, t, q, 1.0, max_iterations=5, log=lambda s: None, check=check)
    assert calls == [1] and solves == []
