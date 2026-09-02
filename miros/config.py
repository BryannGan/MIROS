"""
case.yaml — the single place every answer to the pipeline lives.

Loading is strict: unknown keys are errors (so a typo cannot silently fall
back to a default), and values are validated once, up front.
"""
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, get_args, get_origin

import yaml

STAGES = ['preprocess', 'inflow', 'rom_model', 'tune', 'sim_0d', 'extract_0d',
          'volume_mesh', 'sim_1d', 'extract_1d']


class ConfigError(ValueError):
    pass


@dataclass
class ModelConfig:
    surface: str = 'input/surface.vtp'
    units: str = 'cm'                          # cm | mm (mm is converted to cm)
    inlet: Optional[str] = None                # cap name; None = largest cap
    cap_names: Optional[List[str]] = None      # names for caps in decreasing-area order
    outlets: List[Dict[str, Any]] = field(default_factory=list)   # cut planes for a closed surface
    remesh: bool = False
    remesh_edge_size: Optional[float] = None   # None = estimated from the model


@dataclass
class InflowConfig:
    source: str = 'file'                       # file | gui
    file: Optional[str] = 'input/inflow.flow'
    heart_rate_bpm: float = 60.0               # gui only
    points_per_cycle: int = 1200               # gui only
    peak_flow_mL_s: Optional[float] = None     # gui axis bound


@dataclass
class PressureTarget:
    at: str = 'inlet'                          # 'inlet' or an outlet name
    systolic: float = 120.0
    diastolic: float = 80.0
    mean: Optional[float] = None


@dataclass
class BoundaryConditionsConfig:
    mode: str = 'tune'                         # tune | file
    file: Optional[str] = None                 # rcrt.dat for mode: file
    flow_split: Dict[str, float] = field(default_factory=dict)   # percent per outlet
    pressure_mmHg: PressureTarget = field(default_factory=PressureTarget)
    tolerance_pct: float = 5.0
    max_iterations: int = 12
    rp_fraction: float = 0.09                  # Rp / (Rp + Rd)
    tuning_cycles: int = 5                     # 0D cycles per tuning solve


@dataclass
class MaterialConfig:
    olufsen_k1: float = 0.0
    olufsen_k2: float = -22.5267
    olufsen_k3: float = 1.0e7
    olufsen_exponent: float = 1.0
    olufsen_pressure: float = 0.0
    linear_ehr: float = 1.0e7
    linear_pressure: float = 0.0


@dataclass
class SimulationConfig:
    cycles: int = 6
    seg_min_num: int = 4
    element_size: float = 0.01
    save_data_freq: int = 5
    density: float = 1.06
    viscosity: float = 0.04
    material: MaterialConfig = field(default_factory=MaterialConfig)
    run_1d: bool = True
    max_1d_retries: int = 3


@dataclass
class OutputsConfig:
    volume_projection: bool = False
    plots: bool = True


@dataclass
class SolversConfig:
    onedsolver: Optional[str] = None           # path; None = search


@dataclass
class CaseConfig:
    name: str = 'case'
    model: ModelConfig = field(default_factory=ModelConfig)
    inflow: InflowConfig = field(default_factory=InflowConfig)
    boundary_conditions: BoundaryConditionsConfig = field(default_factory=BoundaryConditionsConfig)
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    outputs: OutputsConfig = field(default_factory=OutputsConfig)
    solvers: SolversConfig = field(default_factory=SolversConfig)

    def section(self, name: str) -> Dict[str, Any]:
        return asdict(getattr(self, name))


# ----------------------------------------------------------------------------

def _coerce(ftype, v, where: str):
    """
    Coerce a scalar to the declared field type. PyYAML reads `1.0e7` as a
    string (YAML 1.1 wants `1.0e+7`), so numbers are converted explicitly
    and anything that is not a number is a clear error.
    """
    origin = get_origin(ftype)
    if origin is Union:                                  # Optional[T]
        args = [a for a in get_args(ftype) if a is not type(None)]
        if v is None:
            return None
        return _coerce(args[0], v, where) if len(args) == 1 else v
    if ftype is bool:
        if isinstance(v, bool):
            return v
        raise ConfigError("%s: expected true/false, got %r" % (where, v))
    if ftype is float:
        if isinstance(v, bool):
            raise ConfigError("%s: expected a number, got %r" % (where, v))
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ConfigError("%s: expected a number, got %r" % (where, v))
    if ftype is int:
        if isinstance(v, bool) or (isinstance(v, float) and not float(v).is_integer()):
            raise ConfigError("%s: expected an integer, got %r" % (where, v))
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ConfigError("%s: expected an integer, got %r" % (where, v))
    if ftype is str:
        return str(v) if v is not None else None
    if origin is dict:
        if not isinstance(v, dict):
            raise ConfigError("%s: expected a mapping, got %r" % (where, v))
        kt, vt = get_args(ftype) or (str, Any)
        return {str(k): (_coerce(vt, x, where + '.' + str(k)) if vt in (float, int, bool, str) else x)
                for k, x in v.items()}
    if origin is list:
        if not isinstance(v, list):
            raise ConfigError("%s: expected a list, got %r" % (where, v))
        (et,) = get_args(ftype) or (Any,)
        return [(_coerce(et, x, where) if et in (float, int, bool, str) else x) for x in v]
    return v


def _from_dict(cls, data: Any, where: str):
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ConfigError("%s: expected a mapping, got %s" % (where, type(data).__name__))
    valid = {f.name: f for f in fields(cls)}
    unknown = sorted(set(data) - set(valid))
    if unknown:
        raise ConfigError("%s: unknown key(s) %s; valid keys: %s" % (where, unknown, sorted(valid)))
    kwargs = {}
    for k, v in data.items():
        ftype = valid[k].type
        if isinstance(ftype, type) and is_dataclass(ftype):
            kwargs[k] = _from_dict(ftype, v, where + '.' + k)
        else:
            kwargs[k] = _coerce(ftype, v, where + '.' + k)
    return cls(**kwargs)


def validate(cfg: CaseConfig) -> None:
    m, i, bc, s = cfg.model, cfg.inflow, cfg.boundary_conditions, cfg.simulation
    if m.units not in ('cm', 'mm'):
        raise ConfigError("model.units must be 'cm' or 'mm', got %r" % m.units)
    if i.source not in ('file', 'gui'):
        raise ConfigError("inflow.source must be 'file' or 'gui', got %r" % i.source)
    if i.source == 'file' and not i.file:
        raise ConfigError("inflow.file is required when inflow.source is 'file'")
    if i.points_per_cycle < 50:
        raise ConfigError("inflow.points_per_cycle must be at least 50")
    if bc.mode not in ('tune', 'file'):
        raise ConfigError("boundary_conditions.mode must be 'tune' or 'file', got %r" % bc.mode)
    if bc.mode == 'file' and not bc.file:
        raise ConfigError("boundary_conditions.file is required when mode is 'file'")
    if bc.mode == 'tune':
        if not bc.flow_split:
            raise ConfigError("boundary_conditions.flow_split is required when mode is 'tune' "
                              "(percent of flow per outlet name)")
        total = sum(bc.flow_split.values())
        if abs(total - 100.0) > 0.5:
            raise ConfigError("boundary_conditions.flow_split sums to %.1f, must be 100" % total)
        if any(v <= 0 for v in bc.flow_split.values()):
            raise ConfigError("every flow_split entry must be positive")
        p = bc.pressure_mmHg
        if p.systolic <= p.diastolic:
            raise ConfigError("pressure_mmHg.systolic must exceed diastolic")
        if p.mean is not None and not (p.diastolic < p.mean < p.systolic):
            raise ConfigError("pressure_mmHg.mean must lie between diastolic and systolic")
        if not (0 < bc.rp_fraction < 1):
            raise ConfigError("boundary_conditions.rp_fraction must be in (0, 1)")
    if s.cycles < 1 or bc.tuning_cycles < 2:
        raise ConfigError("simulation.cycles must be >= 1 and tuning_cycles >= 2")
    if s.seg_min_num < 1:
        raise ConfigError("simulation.seg_min_num must be >= 1")


def load_config(path) -> CaseConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError("case file not found: %s" % path)
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    cfg = _from_dict(CaseConfig, data, 'case')
    validate(cfg)
    return cfg


def save_config(cfg: CaseConfig, path) -> None:
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        yaml.safe_dump(asdict(cfg), f, sort_keys=False, default_flow_style=False)


TEMPLATE = """\
# MIROS case file. Every answer the pipeline needs lives here; `miros run`
# never asks anything. Paths are relative to this file's directory.
name: {name}

model:
  surface: {surface}
  units: {units}                # cm | mm  (mm models are converted to cm)
  inlet: {inlet}                # cap name; null = the largest cap
  # caps are named cap_1, cap_2, ... in decreasing-area order; give your own
  # names here (same order) if you prefer, e.g. [aorta_root, desc_aorta, ...]
  cap_names: null
  outlets: []                   # cut planes for a still-closed surface (phase 5)
  remesh: false                 # usually unnecessary; centerlines work on the raw surface
  remesh_edge_size: null

inflow:
  source: {inflow_source}       # file | gui
  file: {inflow_file}
  heart_rate_bpm: 60            # gui only
  points_per_cycle: 1200        # gui only
  peak_flow_mL_s: null          # gui axis bound

boundary_conditions:
  mode: tune                    # tune | file (file: give an rcrt.dat below)
  file: null
  flow_split:                   # percent of flow per outlet, must sum to 100
{flow_split}
  pressure_mmHg:
    at: inlet                   # 'inlet' or an outlet name
    systolic: 120
    diastolic: 80
    mean: null                  # optional third target
  tolerance_pct: 5
  max_iterations: 12
  rp_fraction: 0.09             # Rp / (Rp + Rd)
  tuning_cycles: 5              # 0D cycles per tuning solve

simulation:
  cycles: 6
  seg_min_num: 4
  element_size: 0.01
  save_data_freq: 5
  density: 1.06
  viscosity: 0.04
  material:                     # Olufsen 1999 defaults
    olufsen_k1: 0.0
    olufsen_k2: -22.5267
    olufsen_k3: 1.0e+7
    olufsen_exponent: 1.0
    olufsen_pressure: 0.0
    linear_ehr: 1.0e+7
    linear_pressure: 0.0
  run_1d: true
  max_1d_retries: 3

outputs:
  volume_projection: false      # tetgen volume mesh + 3D projection of 1D results
  plots: true

solvers:
  onedsolver: {onedsolver}      # path to the OneDSolver executable; null = search
"""


def write_template(path, name='case', surface='input/surface.vtp', units='cm', inlet=None,
                   inflow_file='input/inflow.flow', inflow_source='file', outlet_names=None,
                   onedsolver=None) -> None:
    if outlet_names:
        share = 100.0 / len(outlet_names)
        split = '\n'.join('    %s: %s' % (n, ('%.4g' % share)) for n in outlet_names)
    else:
        split = '    # cap_2: 50\n    # cap_3: 50'
    text = TEMPLATE.format(name=name, surface=surface, units=units,
                           inlet=inlet if inlet else 'null', inflow_source=inflow_source,
                           inflow_file=inflow_file if inflow_file else 'null', flow_split=split,
                           onedsolver=onedsolver if onedsolver else 'null')
    Path(path).write_text(text, encoding='utf-8', newline='\n')
