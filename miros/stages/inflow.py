"""
inflow: one cardiac cycle of inflow.

source: file  -> read inflow.file
source: gui   -> use inflow.file if it exists (drawn earlier with `miros inflow edit`
                 or by a previous run), otherwise open the editor and save the
                 result to inflow.file so the next run does not ask again.
Redrawing the waveform changes the file, which makes this stage stale.
"""
import numpy as np

from ..io import inflow as IO
from ..manifest import file_hash, value_hash
from ..ui import console


def _target(case):
    i = case.config.inflow
    return case.resolve(i.file) if i.file else case.dir / 'input' / 'inflow.flow'


def inputs(case):
    d = {'inflow': value_hash(case.config.section('inflow'))}
    f = _target(case)
    if f.exists():
        d['file'] = file_hash(f)
    elif case.config.inflow.source == 'file':
        raise FileNotFoundError("inflow file not found: %s (draw one with `miros inflow edit` or set inflow.file)" % f)
    return d


def outputs(case):
    return [case.inflow_work]


def run(case):
    i = case.config.inflow
    f = _target(case)
    if f.exists():
        t, q = IO.read_inflow(f)
        console.info("inflow from %s" % f)
    else:
        from ..ui.waveform_editor import edit_waveform
        console.info("no inflow file yet; opening the waveform editor (close the window when done)")
        t, q = edit_waveform(i.heart_rate_bpm, i.points_per_cycle, i.peak_flow_mL_s)
        f.parent.mkdir(parents=True, exist_ok=True)
        IO.write_inflow(t, q, f)
        console.info("saved the drawn waveform to %s; `miros inflow edit` redraws it" % f)
    if len(t) < 50 or np.any(np.diff(t) <= 0):
        raise ValueError("inflow must have >= 50 rows with strictly increasing time")
    t = t - t[0]
    case.work.mkdir(parents=True, exist_ok=True)
    IO.write_inflow(t, q, case.inflow_work)
    tz = getattr(np, 'trapezoid', None) or np.trapz
    console.info("cycle %.3f s, %d points, mean %.1f mL/s, peak %.1f mL/s" % (
        t[-1], len(t), tz(q, t) / (t[-1] - t[0]), q.max()))
    return outputs(case)
