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
    # write None as an explicit `null` instead of leaving the key blank
    y.representer.add_representer(type(None), lambda r, d: r.represent_scalar('tag:yaml.org,2002:null', 'null'))
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


def set_seeds(path, seeds) -> None:
    """segmentation.seeds = [{point, direction, radius}, ...] in flow style, keeping comments."""
    path = Path(path)
    y = _yaml()
    with open(path, 'r', encoding='utf-8') as f:
        data = y.load(f) or CommentedMap()
    sg = data.setdefault('segmentation', CommentedMap())
    seq = CommentedSeq()
    for s in seeds:
        m = CommentedMap()
        m['point'] = [round(float(v), 4) for v in s['point']]
        m['direction'] = [round(float(v), 4) for v in s['direction']]
        m['radius'] = round(float(s['radius']), 4)
        m.fa.set_flow_style()
        seq.append(m)
    sg['seeds'] = seq
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


def set_outlets(path, planes) -> None:
    """model.outlets = the reviewed cut planes (flow style, one line each)."""
    path = Path(path)
    y = _yaml()
    with open(path, 'r', encoding='utf-8') as f:
        data = y.load(f) or CommentedMap()
    model = data.setdefault('model', CommentedMap())
    seq = CommentedSeq()
    for p in planes:
        m = CommentedMap()
        m['name'] = str(p.get('name', ''))
        m['origin'] = [round(float(v), 5) for v in p['origin']]
        m['normal'] = [round(float(v), 6) for v in p['normal']]
        m['radius'] = round(float(p['radius']), 5)
        m['inlet'] = bool(p.get('inlet', False))
        m['use'] = bool(p.get('use', True))
        m.fa.set_flow_style()
        seq.append(m)
    model['outlets'] = seq
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        y.dump(data, f)
