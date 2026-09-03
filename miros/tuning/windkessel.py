"""
Physics-first RCR tuning.

State: per-outlet total resistance R_i, one proximal fraction f = Rp/(Rp+Rd)
shared by all outlets, and one total compliance C distributed C_i = C s_i
(so every outlet has the same RC time constant).

A. Analytic initialization (no solves). With mean inflow Q and target mean
   pressure P: network resistance R = P/Q; outlet i with flow fraction s_i
   gets R_i = R/s_i minus the 0D vessel resistance on its path. The pulse
   pressure has a floor set by the proximal resistances, Rp_net (Qmax - Qmin),
   so f starts at min(f_config, 0.5 PP_target / ((Qmax - Qmin) R)). C from
   the diastolic decay time constant tau = T_dia / ln(P_sys/P_dia): C = tau/R.

B. Fixed-point loop. Run the 0D model, measure achieved flow fractions q_i
   and the pressure waveform at the target location, then update
   multiplicatively (damped, exponent a):

     splits   R_i <- R_i (q_i / s_i)^a
     level    all R scaled by ((sys_t + dia_t) / (sys + dia))^a, or by
              (mean_t / mean)^a when a mean target is given — never by an
              assumed mean, because the mean's position between systolic
              and diastolic depends on the waveform shape
     pulse    f <- f (PP / PP_t)^(-a) (proximal resistance is the direct
              pulse knob); when f reaches a bound, C takes over
     shape    with a mean target, C <- C (s / s_t)^a where
              s = (mean - dia) / PP: a slower diastolic decay (larger
              tau = Rd C) keeps the diastolic value closer to the mean,
              i.e. lowers s

   The problem is close to linear in these variables and converges in a
   handful of solves; the loop returns its best iterate and says when a
   pulse-pressure target is out of reach.
"""
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from ..io import zerod as Z
from ..io.rcrt import RCR

C_MIN, C_MAX = 1e-5, 5e-3          # total compliance bounds, cm^5/dyn (~0.013 .. 6.7 mL/mmHg)
F_MIN, F_MAX = 0.01, 0.5           # proximal fraction bounds


@dataclass
class Targets:
    flow_split: Dict[str, float]        # fraction (sums to 1) per outlet name
    at: str = 'inlet'
    systolic: float = 120.0
    diastolic: float = 80.0
    mean: Optional[float] = None

    @property
    def mean_target(self) -> float:
        return self.mean if self.mean is not None else self.diastolic + (self.systolic - self.diastolic) / 3.0

    @property
    def pulse(self) -> float:
        return self.systolic - self.diastolic


@dataclass
class TuningReport:
    converged: bool
    iterations: int
    solves: int
    seconds: float
    targets: dict
    achieved: dict
    errors_pct: dict
    stop_reason: str = ''
    note: str = ''
    final_state: dict = field(default_factory=dict)
    history: List[dict] = field(default_factory=list)
    initial: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ('converged', 'stop_reason', 'note', 'iterations', 'solves', 'seconds',
                                              'targets', 'achieved', 'errors_pct', 'final_state', 'initial', 'history')}


def _trapezoid(y, x):
    return (getattr(np, 'trapezoid', None) or np.trapz)(y, x)


def _diastole_duration(t: np.ndarray, q: np.ndarray) -> float:
    """Time per cycle with inflow below 10% of its peak (fallback: half the cycle)."""
    T = t[-1] - t[0]
    frac = (q < 0.1 * q.max()).mean()
    return float(T * frac) if 0.15 < frac < 0.85 else 0.5 * T


def build_rcr(R: Dict[str, float], f: float, C_total: float, split: Dict[str, float]) -> RCR:
    return {cap: {'Rp': f * R[cap], 'Rd': (1.0 - f) * R[cap], 'C': C_total * split[cap]} for cap in R}


def analytic_initial_state(cfg: dict, vmap: Z.VesselMap, targets: Targets, t: np.ndarray, q: np.ndarray,
                           rp_fraction: float = 0.09):
    """Returns (R per outlet, f, C_total)."""
    Q = float(_trapezoid(q, t) / (t[-1] - t[0]))
    if Q <= 0:
        raise ValueError("mean inflow must be positive to tune boundary conditions")
    P_mean = targets.mean_target * Z.MMHG_TO_CGS
    R_net = P_mean / Q
    R_path = Z.path_resistance(cfg, vmap)
    R = {}
    for cap in vmap.outlet_names:
        s = targets.flow_split[cap]
        R_needed = R_net / s
        R[cap] = max(R_needed - R_path.get(cap, 0.0), 0.1 * R_needed)
    # proximal fraction: leave at most half the target pulse to Rp_net * (Qmax - Qmin)
    dQ = float(q.max() - q.min())
    f_pulse = 0.5 * targets.pulse * Z.MMHG_TO_CGS / (dQ * R_net) if dQ > 0 else rp_fraction
    f = float(np.clip(min(rp_fraction, f_pulse), F_MIN, F_MAX))
    tau = _diastole_duration(t, q) / np.log(targets.systolic / targets.diastolic)
    C_total = float(np.clip(tau / R_net, C_MIN, C_MAX))
    return R, f, C_total


def _measure(cfg: dict, rcr: RCR, vmap: Z.VesselMap, targets: Targets, cycle_duration: float, cycles: int):
    df = Z.run(Z.set_cycles(Z.apply_rcr(cfg, rcr, vmap), cycles))
    last = Z.last_cycle(df, cycle_duration)
    flows = Z.outlet_flows(last, vmap)
    tot = sum(flows.values())
    fractions = {k: v / tot for k, v in flows.items()} if tot > 0 else {k: 0.0 for k in flows}
    return fractions, Z.pressure_at(last, vmap, targets.at)


def _errors_pct(fractions, pressure, targets: Targets) -> Dict[str, float]:
    e = {'flow_' + k: 100.0 * (fractions[k] - s) / s for k, s in targets.flow_split.items()}
    e['systolic'] = 100.0 * (pressure['systolic'] - targets.systolic) / targets.systolic
    e['diastolic'] = 100.0 * (pressure['diastolic'] - targets.diastolic) / targets.diastolic
    if targets.mean is not None:
        e['mean'] = 100.0 * (pressure['mean'] - targets.mean) / targets.mean
    return e


def tune(cfg: dict, outlet_names: Sequence[str], targets: Targets, t: np.ndarray, q: np.ndarray,
         cycle_duration: float, tolerance_pct: float = 5.0, max_iterations: int = 12,
         rp_fraction: float = 0.09, cycles: int = 5, damping: float = 0.8, log=print):
    """Returns (rcr, TuningReport)."""
    vmap = Z.VesselMap(cfg, outlet_names)
    missing = [c for c in outlet_names if c not in targets.flow_split]
    if missing:
        raise ValueError("flow_split has no entry for outlet(s): %s" % missing)
    split = targets.flow_split
    t0 = time.time()
    R, f, C = analytic_initial_state(cfg, vmap, targets, t, q, rp_fraction)
    initial = {'R': dict(R), 'rp_fraction': f, 'C_total': C}
    history, solves, converged = [], 0, False
    alpha = damping
    fractions = pressure = errors = None
    prev = None
    best = None                      # (worst, rcr, fractions, pressure, errors, (R, f, C))
    stop_reason = 'max_iterations'
    since_improvement = 0
    rcr = build_rcr(R, f, C, split)

    for it in range(1, max_iterations + 1):
        try:
            fractions, pressure = _measure(cfg, rcr, vmap, targets, cycle_duration, cycles)
            solves += 1
        except Exception as e:                    # diverged: back off toward the previous iterate
            if prev is None:
                raise
            log("  iteration %d: solve failed (%s); halving the step" % (it, str(e)[:60]))
            alpha *= 0.5
            R, f, C = prev
            rcr = build_rcr(R, f, C, split)
            continue
        errors = _errors_pct(fractions, pressure, targets)
        worst = max(abs(v) for v in errors.values())
        history.append({'iteration': it, 'fractions': fractions, 'pressure': pressure, 'errors_pct': errors,
                        'worst_pct': worst, 'rp_fraction': f, 'C_total': C})
        log("  iteration %2d: worst %5.1f%% | P %5.1f/%5.1f mean %5.1f | f %.3f C %.2e | splits %s" % (
            it, worst, pressure['systolic'], pressure['diastolic'], pressure['mean'], f, C,
            ' '.join('%s=%.1f' % (k, 100 * v) for k, v in fractions.items())))
        if best is None or worst < best[0] - 0.3:
            best = (worst, rcr, fractions, pressure, errors, (dict(R), f, C))
            since_improvement = 0
        else:
            since_improvement += 1
        if worst <= tolerance_pct:
            converged, stop_reason = True, 'converged'
            break
        if since_improvement >= 4:
            stop_reason = 'stagnated'
            break
        prev = (dict(R), f, C)
        sys_p, dia_p, mean_p = pressure['systolic'], pressure['diastolic'], pressure['mean']
        # flow splits and pressure level -> resistances
        if targets.mean is not None:
            level = (targets.mean / max(mean_p, 1e-6)) ** alpha
        else:
            level = ((targets.systolic + targets.diastolic) / max(sys_p + dia_p, 1e-6)) ** alpha
        R = {cap: float(np.clip(R[cap] * (fractions[cap] / split[cap]) ** alpha * level, 1.0, 1e8)) for cap in R}
        # pulse pressure -> proximal fraction; compliance takes over at the bounds of f
        pp = sys_p - dia_p
        rho = pp / targets.pulse if pp > 0 else 1.0
        f_new = float(np.clip(f * rho ** (-alpha), F_MIN, F_MAX))
        if f_new == f and f in (F_MIN, F_MAX):
            C = float(np.clip(C * rho ** alpha, C_MIN, C_MAX))
        f = f_new
        # waveform shape (only with a mean target) -> compliance through the diastolic time constant
        if targets.mean is not None and pp > 0:
            s = (mean_p - dia_p) / pp
            s_t = (targets.mean - targets.diastolic) / targets.pulse
            if s > 0:
                C = float(np.clip(C * (s / s_t) ** alpha, C_MIN, C_MAX))
        rcr = build_rcr(R, f, C, split)

    if best is not None and not converged:
        _, rcr, fractions, pressure, errors, (R, f, C) = best      # hand back the best iterate, not the last
    note = ''
    if not converged and pressure is not None and errors is not None:
        pp = pressure['systolic'] - pressure['diastolic']
        pulse_limited = (pp > targets.pulse * (1 + tolerance_pct / 100.0)
                         and errors['systolic'] > 0 and errors['diastolic'] < 0)
        if pulse_limited:
            note = ("the pulse pressure at '%s' cannot be brought to %.0f mmHg with this inflow waveform; the best "
                    "trade-off found is %.0f mmHg (%.0f/%.0f). The mean pressure and the flow splits are on target; "
                    "the remaining pulse comes from inertial and viscous pressure drops along the vessels "
                    "(peak-to-trough inflow %.0f mL/s), which no outlet RCR can remove. Options: target an outlet "
                    "instead of the inlet, use a smoother inflow waveform, or accept these values."
                    % (targets.at, targets.pulse, pp, pressure['systolic'], pressure['diastolic'],
                       float(q.max() - q.min())))
    report = TuningReport(
        converged=converged, stop_reason=stop_reason, note=note, iterations=len(history), solves=solves,
        seconds=time.time() - t0,
        targets={'flow_split': split, 'at': targets.at, 'systolic': targets.systolic,
                 'diastolic': targets.diastolic, 'mean': targets.mean},
        achieved={'flow_split': fractions, 'pressure': pressure},
        errors_pct=errors or {}, final_state={'R': R, 'rp_fraction': f, 'C_total': C},
        history=history, initial=initial)
    return rcr, report
