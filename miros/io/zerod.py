"""
svZeroDSolver input (JSON) and results: load, map outlets to vessels, apply
boundary conditions, run, and read last-cycle metrics.

Outlet <-> vessel mapping is read from the JSON, never inferred from vessel
names: the ROM builder names each outlet BC 'RCR_<k>' where k is the cap's
index in centerlines_outlets.dat, and tags the vessel with
boundary_conditions.outlet = 'RCR_<k>'.
"""
import json
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .rcrt import RCR

MMHG_TO_CGS = 1333.22


def load(path) -> dict:
    with open(path, 'r') as f:
        cfg = json.load(f)
    if 'boundary_conditions' not in cfg or 'vessels' not in cfg:
        raise ValueError("%s is not a svZeroDSolver input (missing boundary_conditions/vessels)" % path)
    return cfg


def save(cfg: dict, path) -> None:
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(cfg, f, indent=4, sort_keys=True)


class VesselMap:
    """cap name -> vessel carrying its RCR; plus the inlet vessel."""

    def __init__(self, cfg: dict, outlet_names: Sequence[str]):
        bc_to_vessel = {}
        self.inlet_vessel: Optional[str] = None
        for v in cfg.get('vessels', []):
            bcs = v.get('boundary_conditions') or {}
            if 'outlet' in bcs:
                bc_to_vessel[bcs['outlet']] = v['vessel_name']
            if 'inlet' in bcs:
                self.inlet_vessel = v['vessel_name']
        if self.inlet_vessel is None:
            raise ValueError("0D input has no vessel with an inlet boundary condition")
        rcr_names = {bc['bc_name'] for bc in cfg.get('boundary_conditions', []) if bc.get('bc_type') == 'RCR'}
        if len(rcr_names) != len(outlet_names):
            raise ValueError("0D input has %d RCR boundary conditions but %d outlet names were given"
                             % (len(rcr_names), len(outlet_names)))
        self.outlet_vessel: Dict[str, str] = {}
        self.bc_name: Dict[str, str] = {}
        for k, cap in enumerate(outlet_names):
            name = 'RCR_%d' % k
            if name not in bc_to_vessel:
                raise ValueError("outlet %s (%s) has no vessel in the 0D input; regenerate the ROM model" % (cap, name))
            self.outlet_vessel[cap] = bc_to_vessel[name]
            self.bc_name[cap] = name
        self.outlet_names = list(outlet_names)

    def vessel_for(self, cap: str) -> str:
        return self.inlet_vessel if cap == 'inlet' else self.outlet_vessel[cap]


def apply_rcr(cfg: dict, rcr: RCR, vmap: VesselMap) -> dict:
    """New config with RCR values set per outlet (deep copy)."""
    out = deepcopy(cfg)
    by_name = {vmap.bc_name[cap]: cap for cap in vmap.outlet_names}
    for bc in out['boundary_conditions']:
        if bc.get('bc_type') == 'RCR':
            cap = by_name[bc['bc_name']]
            if cap not in rcr:
                raise ValueError("no RCR values for outlet %s" % cap)
            p = rcr[cap]
            bc['bc_values']['Rp'] = float(p['Rp'])
            bc['bc_values']['C'] = float(p['C'])
            bc['bc_values']['Rd'] = float(p['Rd'])
            bc['bc_values'].setdefault('Pd', 0.0)
    return out


def set_cycles(cfg: dict, cycles: int) -> dict:
    out = deepcopy(cfg)
    out['simulation_parameters']['number_of_cardiac_cycles'] = int(cycles)
    return out


def run(cfg: dict) -> pd.DataFrame:
    """Run svZeroDSolver on an in-memory config; full results as a DataFrame."""
    import pysvzerod
    solver = pysvzerod.Solver(cfg)
    solver.run()
    df = pd.DataFrame(solver.get_full_result())
    for col in ('pressure_in', 'pressure_out', 'flow_in', 'flow_out'):
        if not np.isfinite(df[col].to_numpy()).all():
            raise RuntimeError("0D solution contains non-finite values in %s" % col)
    return df


def last_cycle(df: pd.DataFrame, cycle_duration: float) -> pd.DataFrame:
    t_max = df['time'].max()
    n = int(np.floor(t_max / cycle_duration + 1e-6))
    start = (n - 1) * cycle_duration if n >= 1 else 0.0
    return df[df['time'] >= start - 1e-9]


def outlet_flows(last: pd.DataFrame, vmap: VesselMap) -> Dict[str, float]:
    """Mean |outflow| per outlet over the given (last-cycle) frame."""
    g = last.groupby('name')['flow_out'].mean()
    return {cap: float(abs(g.get(vmap.outlet_vessel[cap], 0.0))) for cap in vmap.outlet_names}


def pressure_at(last: pd.DataFrame, vmap: VesselMap, at: str) -> Dict[str, float]:
    """Systolic / diastolic / mean pressure in mmHg at 'inlet' or an outlet name."""
    vessel = vmap.vessel_for(at)
    col = 'pressure_in' if at == 'inlet' else 'pressure_out'
    p = last.loc[last['name'] == vessel, col].to_numpy() / MMHG_TO_CGS
    if len(p) == 0:
        raise RuntimeError("no 0D results for vessel %s" % vessel)
    return {'systolic': float(p.max()), 'diastolic': float(p.min()), 'mean': float(p.mean())}


def path_resistance(cfg: dict, vmap: VesselMap) -> Dict[str, float]:
    """Sum of Poiseuille resistances of the vessels from the inlet to each outlet."""
    R = {v['vessel_id']: v['zero_d_element_values'].get('R_poiseuille', 0.0) for v in cfg['vessels']}
    name_to_id = {v['vessel_name']: v['vessel_id'] for v in cfg['vessels']}
    parent: Dict[int, int] = {}
    for j in cfg.get('junctions', []):
        for o in j['outlet_vessels']:
            parent[o] = j['inlet_vessels'][0]
    out = {}
    for cap in vmap.outlet_names:
        vid = name_to_id[vmap.outlet_vessel[cap]]
        total = 0.0
        seen = set()
        while vid is not None and vid not in seen:
            seen.add(vid)
            total += R.get(vid, 0.0)
            vid = parent.get(vid)
        out[cap] = total
    return out


def results_to_csv(df: pd.DataFrame, path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
