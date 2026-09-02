"""
Targeted edits to an existing case.yaml that keep its comments (ruamel.yaml
round-trip). Used by the interactive tools; hand edits remain the normal way.
"""
from pathlib import Path
from typing import Dict, Optional, Sequence

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 120
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def update_case_yaml(path, *, inlet: Optional[str] = None, cap_names: Optional[Sequence[str]] = None,
                     flow_split: Optional[Dict[str, float]] = None, pressure: Optional[dict] = None,
                     units: Optional[str] = None) -> None:
    """
    pressure: {'at': str, 'systolic': float, 'diastolic': float, 'mean': float | None}
    cap_names: names for the caps in decreasing-area order (all caps, inlet included)
    """
    path = Path(path)
    y = _yaml()
    with open(path, 'r', encoding='utf-8') as f:
        data = y.load(f) or CommentedMap()

    model = data.setdefault('model', CommentedMap())
    if units is not None:
        model['units'] = units
    if inlet is not None:
        model['inlet'] = inlet
    if cap_names is not None:
        seq = CommentedSeq([str(n) for n in cap_names])
        seq.fa.set_flow_style()
        model['cap_names'] = seq

    bc = data.setdefault('boundary_conditions', CommentedMap())
    if flow_split is not None:
        fs = CommentedMap()
        for k, v in flow_split.items():
            fs[str(k)] = round(float(v), 4)
        bc['flow_split'] = fs
    if pressure is not None:
        p = bc.get('pressure_mmHg')
        if not isinstance(p, CommentedMap):
            p = CommentedMap()
            bc['pressure_mmHg'] = p
        p['at'] = str(pressure['at'])
        p['systolic'] = float(pressure['systolic'])
        p['diastolic'] = float(pressure['diastolic'])
        p['mean'] = None if pressure.get('mean') is None else float(pressure['mean'])

    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        y.dump(data, f)


def set_values(path, values: Dict[str, object]) -> None:
    """Set dotted keys, e.g. {'simulation.run_1d': False, 'model.units': 'mm'}, keeping comments."""
    path = Path(path)
    y = _yaml()
    with open(path, 'r', encoding='utf-8') as f:
        data = y.load(f) or CommentedMap()
    for dotted, value in values.items():
        node = data
        keys = dotted.split('.')
        for k in keys[:-1]:
            if not isinstance(node.get(k), CommentedMap):
                node[k] = CommentedMap()
            node = node[k]
        node[keys[-1]] = value
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        y.dump(data, f)
