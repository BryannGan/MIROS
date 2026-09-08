"""
Running an external program with its output streamed, logged, and stoppable.

Both long programs MIROS starts (SeqSeg, OneDSolver) go through
run_logged(): the program's output goes to a log file as before, every line
can also be handed to a callback while the program runs, the caller may poll
something of its own between checks (SeqSeg keeps its step counter in a
file), and a threading.Event stops the program. Stopping kills the whole
process tree, because nnU-Net forks workers, and it happens on Ctrl-C too:
the program is started in its own session, so the terminal's SIGINT does
not reach it and it would otherwise keep running after MIROS has quit.
"""
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Sequence


class RunCancelled(Exception):
    """The run was stopped on request (Stop button, cancel event): not a failure."""


_ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')


def strip_ansi(s: str) -> str:
    return _ANSI.sub('', s)


def kill_tree(proc: subprocess.Popen, grace: float = 5.0) -> None:
    """
    Stop `proc` and everything it started. POSIX: SIGTERM to its process
    group, SIGKILL after `grace` seconds. Windows: taskkill /T /F.
    The process must have been started by run_logged (own session/group).
    """
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        if os.name != 'nt':
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass


def _pump(stream, log_file, on_line: Optional[Callable[[str], None]]) -> None:
    """Reader thread: raw bytes to the log file, decoded lines (split on \\r and \\n) to on_line."""
    buf = b''
    while True:
        try:
            chunk = stream.read(4096)
        except (OSError, ValueError):
            break
        if not chunk:
            break
        try:
            log_file.write(chunk)
            log_file.flush()
        except (OSError, ValueError):       # the log was closed under us after a kill
            pass
        buf += chunk
        while True:
            m = re.search(rb'[\r\n]', buf)
            if not m:
                break
            line, buf = buf[:m.start()], buf[m.end():]
            if on_line is not None and line.strip():
                on_line(line.decode('utf-8', 'replace'))
    if on_line is not None and buf.strip():
        on_line(buf.decode('utf-8', 'replace'))


def run_logged(cmd: Sequence, log, cwd=None, env: Optional[dict] = None,
               on_line: Optional[Callable[[str], None]] = None,
               cancel: Optional[threading.Event] = None,
               poll: Optional[Callable[[], None]] = None, poll_interval: float = 0.5,
               timeout: Optional[float] = None, grace: float = 5.0, name: Optional[str] = None) -> int:
    """
    Run `cmd`, writing everything it prints (stdout and stderr, in order) to
    `log`. Returns the exit code.

    on_line(text)   called from a reader thread for every line as it arrives
    cancel          a threading.Event; once set the program is killed and
                    RunCancelled is raised
    poll()          called every `poll_interval` seconds while the program runs,
                    and once more after it ends
    timeout         seconds after which the program is killed (TimeoutExpired)
    name            what to call the program in messages (default: its file name)

    Any exception in the caller's thread, Ctrl-C included, kills the program
    before propagating: it is never left running on its own.
    """
    log = Path(log)
    name = name or Path(str(cmd[0])).name
    log.parent.mkdir(parents=True, exist_ok=True)
    kw = dict(cwd=str(cwd) if cwd else None, env=env, stdin=subprocess.DEVNULL,
              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    if os.name == 'nt':
        kw['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw['start_new_session'] = True
    cmd = [str(c) for c in cmd]
    t0 = time.time()
    with open(log, 'wb') as f:
        proc = subprocess.Popen(cmd, **kw)
        pump = threading.Thread(target=_pump, args=(proc.stdout, f, on_line), daemon=True)
        pump.start()
        try:
            while True:
                try:
                    proc.wait(timeout=poll_interval)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if cancel is not None and cancel.is_set():
                    kill_tree(proc, grace)
                    raise RunCancelled('%s stopped after %.0f s' % (name, time.time() - t0))
                if timeout is not None and time.time() - t0 > timeout:
                    kill_tree(proc, grace)
                    raise subprocess.TimeoutExpired(cmd, timeout)
                if poll is not None:
                    poll()
        except BaseException:                       # noqa: BLE001 - cancel, Ctrl-C, or the poll failing
            kill_tree(proc, grace)
            raise
        finally:
            pump.join(timeout=grace)                # a killed tree closes the pipe; a stray grandchild may not
    if poll is not None:
        poll()
    return proc.returncode
