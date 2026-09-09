"""
Running svOneDSolver and checking that it actually produced results.
"""
import threading
from pathlib import Path
from typing import List, Optional

from .process import run_logged


class OneDSolverError(RuntimeError):
    pass


def run_onedsolver(executable, input_file, workdir, log_name: str = 'onedsolver.log',
                   timeout: Optional[float] = None, cancel: Optional[threading.Event] = None) -> Path:
    """
    Run OneDSolver on `input_file` inside `workdir` (created if needed).

    Success means exit code 0 AND at least one *_flow.dat result file in
    workdir. Raises OneDSolverError with the log tail otherwise, and
    RunCancelled if `cancel` is set while it runs (the solver is killed).
    Returns the log path.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    executable = str(executable)
    if not Path(executable).exists():
        raise OneDSolverError("OneDSolver executable not found: %s" % executable)
    log = workdir / log_name
    code = run_logged([executable, str(Path(input_file).resolve())], log, cwd=workdir,
                      cancel=cancel, timeout=timeout, name='OneDSolver')
    results = list(workdir.glob('*_flow.dat'))
    if code != 0 or not results:
        tail = log.read_text(encoding='utf-8', errors='replace').splitlines()[-25:]
        raise OneDSolverError("OneDSolver failed (exit %d, %d result files). Log tail:\n%s" %
                              (code, len(results), '\n'.join(tail)))
    return log


def result_files(workdir) -> List[Path]:
    return sorted(Path(workdir).glob('*_flow.dat'))
