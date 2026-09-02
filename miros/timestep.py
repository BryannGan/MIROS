"""
Time-step guidance for the inflow waveform.

The 0D and 1D solvers use the waveform's sample spacing as their time
step. svOneDSolver is implicit, so it does not need a Courant number
below one to be stable; a Courant number below ~0.8 is nevertheless a
sound accuracy target, and that is what the recommendation below aims
for:

    CFL = (v_peak + c) * dt / dx        with
    v_peak = Q_peak / A_inlet           peak mean velocity at the inlet
    c      = sqrt((k1 e^{k2 r} + k3) / (2 rho))   Moens-Korteweg wave speed
                                        from the Olufsen wall law at the inlet radius
    dx     = smallest cap diameter      the finest feature the 1D mesh resolves
"""
import math
from typing import Dict, Tuple


def wave_speed(radius_cm: float, k1: float, k2: float, k3: float, density: float) -> float:
    eh_over_r = k1 * math.exp(k2 * radius_cm) + k3          # dyn/cm^2
    return math.sqrt(max(eh_over_r, 1.0) / (2.0 * density))  # cm/s


def recommended_samples_per_cycle(cycle_s: float, q_peak: float, inlet_area_cm2: float, min_cap_area_cm2: float,
                                  k1: float = 0.0, k2: float = -22.5267, k3: float = 1.0e7, density: float = 1.06,
                                  cfl: float = 0.8, minimum: int = 600, round_to: int = 100) -> Tuple[int, Dict[str, float]]:
    """Returns (samples per cycle, the numbers behind it)."""
    v = abs(q_peak) / max(inlet_area_cm2, 1e-9)
    r_in = math.sqrt(inlet_area_cm2 / math.pi)
    c = wave_speed(r_in, k1, k2, k3, density)
    dx = 2.0 * math.sqrt(max(min_cap_area_cm2, 1e-9) / math.pi)
    dt = cfl * dx / (v + c)
    n = int(math.ceil(cycle_s / dt / round_to) * round_to)
    n = max(n, minimum)
    return n, {'v_peak': v, 'wave_speed': c, 'dx': dx, 'dt_ms': 1000.0 * dt, 'cfl': cfl}
