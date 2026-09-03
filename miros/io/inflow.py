"""
Inflow waveform files (.flow): two columns, time [s] and flow [mL/s], one
cardiac cycle, uniformly spaced in time.
"""
from pathlib import Path
from typing import Tuple

import numpy as np


def read_inflow(path) -> Tuple[np.ndarray, np.ndarray]:
    data = np.loadtxt(path)
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError("%s: expected two columns (time, flow)" % path)
    return data[:, 0], data[:, 1]


def write_inflow(time: np.ndarray, flow: np.ndarray, path) -> None:
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        for t, q in zip(time, flow):
            f.write('%.9f %.6f\n' % (t, q))


def cycle_duration(path) -> float:
    t, _ = read_inflow(path)
    return float(t[-1])


def time_step(path) -> float:
    t, _ = read_inflow(path)
    return float((t[-1] - t[0]) / (len(t) - 1))     # not diff()[0]: rounding there drifts over a cycle


def num_time_steps(path, cycles: int) -> int:
    """Total solver time steps for `cycles` cardiac cycles at the file's spacing."""
    t, _ = read_inflow(path)
    return int(cycles * len(t))


def mean_flow(path) -> float:
    t, q = read_inflow(path)
    trapezoid = getattr(np, "trapezoid", None) or np.trapz   # numpy 2 renamed trapz
    return float(trapezoid(q, t) / (t[-1] - t[0]))
