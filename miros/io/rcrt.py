"""
rcrt.dat: RCR (three-element Windkessel) outlet boundary conditions in the
format read by the SimVascular reduced-order model builder.

    2                       <- file header (RCR type marker)
    2                       <- per outlet: number of time points of Pd(t)
    <outlet name>
    <Rp>
    <C>
    <Rd>
    0.0 0.0                 <- (t, Pd) pairs; distal pressure is 0 here
    1.0 0.0
    ... next outlet ...

This is the single implementation; nothing else should hand-write this file.
"""
from pathlib import Path
from typing import Dict, Sequence

RCR = Dict[str, Dict[str, float]]      # {outlet: {'Rp': ., 'C': ., 'Rd': .}}

DEFAULT_RCR = {'Rp': 100.0, 'C': 1e-4, 'Rd': 1000.0}


def read_rcrt(path) -> RCR:
    lines = [l.strip() for l in Path(path).read_text().splitlines() if l.strip()]
    if not lines or lines[0] != '2':
        raise ValueError("%s does not start with the RCR header '2'" % path)
    out: RCR = {}
    i = 1
    while i < len(lines):
        n_pts = int(lines[i])
        name = lines[i + 1]
        rp, c, rd = (float(lines[i + 2]), float(lines[i + 3]), float(lines[i + 4]))
        out[name] = {'Rp': rp, 'C': c, 'Rd': rd}
        i += 5 + n_pts
    return out


def write_rcrt(rcr: RCR, outlet_names: Sequence[str], path) -> None:
    """Write RCRs for `outlet_names` in that order (missing names get DEFAULT_RCR)."""
    lines = ['2']
    for name in outlet_names:
        p = rcr.get(name, DEFAULT_RCR)
        lines += ['2', name, repr(float(p['Rp'])), repr(float(p['C'])), repr(float(p['Rd'])), '0.0 0.0', '1.0 0.0']
    Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


def write_default_rcrt(outlet_names: Sequence[str], path) -> None:
    write_rcrt({}, outlet_names, path)
