"""
Running svOneDSolver and checking that it actually produced results.
"""
import subprocess
from pathlib import Path
from typing import List, Optional


class OneDSolverError(RuntimeError):
    pass


def run_onedsolver(executable, input_file, workdir, log_name: str = 'onedsolver.log',
                   timeout: Optional[float] = None) -> Path:
    """
    Run OneDSolver on `input_file` inside `workdir` (created if needed).

    Success means exit code 0 AND at least one *_flow.dat result file in
    workdir. Raises OneDSolverError with the log tail otherwise.
    Returns the log path.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    executable = str(executable)
    if not Path(executable).exists():
        raise OneDSolverError("OneDSolver executable not found: %s" % executable)
    log = workdir / log_name
    with open(log, 'w', encoding='utf-8', newline='\n') as f:
        proc = subprocess.run([executable, str(Path(input_file).resolve())], cwd=str(workdir),
                              stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
    results = list(workdir.glob('*_flow.dat'))
    if proc.returncode != 0 or not results:
        tail = log.read_text(errors='replace').splitlines()[-25:]
        raise OneDSolverError("OneDSolver failed (exit %d, %d result files). Log tail:\n%s" %
                              (proc.returncode, len(results), '\n'.join(tail)))
    return log


def result_files(workdir) -> List[Path]:
    return sorted(Path(workdir).glob('*_flow.dat'))
