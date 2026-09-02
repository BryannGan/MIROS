"""inflow: one cardiac cycle of inflow, from a file or the interactive editor."""
import numpy as np

from ..io import inflow as IO
from ..manifest import file_hash, value_hash
from ..ui import console


def inputs(case):
    i = case.config.inflow
    d = {'inflow': value_hash(case.config.section('inflow'))}
    if i.source == 'file':
        d['file'] = file_hash(case.resolve(i.file))
    return d


def outputs(case):
    return [case.inflow_work]


def run(case):
    i = case.config.inflow
    if i.source == 'file':
        t, q = IO.read_inflow(case.resolve(i.file))
        if len(t) < 50 or np.any(np.diff(t) <= 0):
            raise ValueError("inflow file must have >= 50 rows with strictly increasing time")
        t = t - t[0]
    else:
        from ..ui.waveform_editor import edit_waveform
        t, q = edit_waveform(i.heart_rate_bpm, i.points_per_cycle, i.peak_flow_mL_s)
    case.work.mkdir(parents=True, exist_ok=True)
    IO.write_inflow(t, q, case.inflow_work)
    tz = getattr(np, 'trapezoid', None) or np.trapz
    console.info("cycle %.3f s, %d points, mean %.1f mL/s, peak %.1f mL/s" % (
        t[-1], len(t), tz(q, t) / (t[-1] - t[0]), q.max()))
    return outputs(case)
