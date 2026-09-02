"""
Validation gate for the builtin centerline backend against the SimVascular
output on the test case: same topology, path lengths within 3%, and a 0D
model that reproduces SimVascular's flow splits within 1 percentage point
with identical RCRs on geometrically matched outlets.
"""
import json

import numpy as np
import pytest
import pyvista as pv

from miros.geometry import caps as C
from miros.geometry.centerline_tree import annotate
from miros.geometry.centerlines import compute_centerlines
from miros.io.rcrt import read_rcrt
from miros.rom.centerlines import Centerlines
from miros.rom.mesh import Mesh, get_connectivity
from miros.rom.parameters import Parameters

pytestmark = pytest.mark.slow


def _endpoint_caps(cl, cap_centroids):
    """column j -> cap name, by the centerline's outlet endpoint."""
    cid = cl['CenterlineId']
    L = cl.lines.reshape(-1, 3)[:, 1:]
    deg = np.bincount(L.ravel(), minlength=cl.n_points)
    out = {}
    for j in range(cid.shape[1]):
        end = [p for p in np.where((cid[:, j] == 1) & (deg == 1))[0] if p != 0][0]
        out[j] = min(cap_centroids, key=lambda k: np.linalg.norm(cap_centroids[k] - cl.points[end]))
    return out


def _path_lengths(cl):
    cid = cl['CenterlineId']
    L = cl.lines.reshape(-1, 3)[:, 1:]
    seg = np.linalg.norm(cl.points[L[:, 1]] - cl.points[L[:, 0]], axis=1)
    return [seg[(cid[L[:, 0], j] == 1) & (cid[L[:, 1], j] == 1)].sum() for j in range(cid.shape[1])]


@pytest.fixture(scope='module')
def built(surface_path, sv_reference, tmp_path_factory):
    surf = C.read_polydata(surface_path)
    caps = C.make_caps(surf)
    sv_caps = {k: np.asarray(v['centroid']) for k, v in json.loads(sv_reference['caps'].read_text()).items()}
    for c in caps:                                   # name caps as SimVascular did
        name = min(sv_caps, key=lambda k: np.linalg.norm(sv_caps[k] - c.centroid))
        c.name, c.is_inlet = name, (name == 'inlet')
    order = [C.inlet_cap(caps)] + sorted(C.outlet_caps(caps), key=lambda c: c.name)
    tree = compute_centerlines(surf, order, verbose=False)
    closed = C.close_surface(surf, order)
    mine = pv.wrap(annotate(tree, closed, verbose=False))
    ref = pv.read(str(sv_reference['centerlines']))
    return dict(tree=tree, mine=mine, ref=ref, sv_caps=sv_caps, order=order, surf=surf,
                out=tmp_path_factory.mktemp('rom'))


def test_topology_matches(built):
    for cl in (built['ref'], built['mine']):
        b, f = cl['BranchId'], cl['BifurcationId']
        assert len(set(b[b >= 0])) == 7 and len(set(f[f >= 0])) == 2
    # same outlet groupings at every junction, in cap terms
    def groups(cl):
        col = _endpoint_caps(cl, built['sv_caps'])
        cid, b = cl['CenterlineId'], cl['BranchId']
        caps_of = lambda br: frozenset(col[j] for j in np.where(cid[b == br].max(axis=0))[0])
        return {frozenset([caps_of(v.inflow)] + [caps_of(o) for o in v.outflow]) for v in get_connectivity(cl).values()}
    assert groups(built['ref']) == groups(built['mine'])


def test_outlet_columns_end_at_named_caps(built):
    col = _endpoint_caps(built['mine'], built['sv_caps'])
    assert [col[j] for j in range(len(col))] == built['tree'].outlet_names


def test_path_lengths_within_3_percent(built):
    ref_by_cap = dict(zip(_endpoint_caps(built['ref'], built['sv_caps']).values(), _path_lengths(built['ref'])))
    mine_by_cap = dict(zip(built['tree'].outlet_names, _path_lengths(built['mine'])))
    for cap, l_ref in ref_by_cap.items():
        assert abs(mine_by_cap[cap] - l_ref) / l_ref < 0.03, cap


def test_end_areas_equal_cap_areas(built):
    cl = built['mine']
    L = cl.lines.reshape(-1, 3)[:, 1:]
    deg = np.bincount(L.ravel(), minlength=cl.n_points)
    cid = cl['CenterlineId']
    for j, cap in enumerate(built['order'][1:]):
        end = [p for p in np.where((cid[:, j] == 1) & (deg == 1))[0] if p != 0][0]
        assert abs(cl['CenterlineSectionArea'][end] - cap.area) / cap.area < 0.02


def test_zerod_model_reproduces_simvascular_flow_splits(built, sv_reference):
    pysvzerod = pytest.importorskip('pysvzerod')
    import pandas as pd
    out = built['out']
    rcrt = sv_reference['rcrt']
    names = built['tree'].outlet_names
    (out / 'centerlines_outlets.dat').write_text('\n'.join(names) + '\n')
    C.write_boundary_dir(built['surf'], built['order'], out / 'caps_and_wall')
    P = Parameters()
    P.output_directory = str(out); P.boundary_surfaces_dir = str(out / 'caps_and_wall')
    P.inlet_face_input_file = 'inlet.vtp'; P.inflow_input_file = str(sv_reference['inflow'])
    P.solver_output_file = 'builtin_0D.json'; P.model_name = 'test'; P.outflow_bc_type = 'rcr'; P.uniform_bc = False
    P.seg_size_adaptive = False; P.seg_min_num = 4; P.outlet_face_names_file = str(out / 'centerlines_outlets.dat')
    P.outflow_bc_file = str(rcrt); P.model_order = 0; P.time_step = 0.0005; P.num_time_steps = 9600
    P.density = 1.06; P.viscosity = 0.04
    assert Mesh().generate(P, Centerlines.from_polydata(built['mine'], names))

    # reference JSON with each cap's RCR on the vessel that really ends at that cap
    rcr = read_rcrt(rcrt)
    col_ref = _endpoint_caps(built['ref'], built['sv_caps'])
    J = json.load(open(sv_reference['zerod']))
    for bc in J['boundary_conditions']:
        if bc['bc_type'] == 'RCR':
            bc['bc_values'].update(rcr[col_ref[int(bc['bc_name'][4:])]])
    json.dump(J, open(out / 'ref_geo.json', 'w'))

    def splits(path, colmap):
        s = pysvzerod.Solver(str(path)); s.run(); df = pd.DataFrame(s.get_full_result())
        cfg = json.load(open(path)); T = 0.6
        n = int(np.floor(df.time.max() / T + 1e-6)); last = df[df.time >= (n - 1) * T]
        vessel = {v['boundary_conditions']['outlet']: v['vessel_name'] for v in cfg['vessels'] if 'outlet' in (v.get('boundary_conditions') or {})}
        q = {colmap[k]: abs(last[last.name == vessel['RCR_%d' % k]].flow_out.mean()) for k in range(len(vessel))}
        tot = sum(q.values())
        return {k: 100 * v / tot for k, v in q.items()}
    ref = splits(out / 'ref_geo.json', col_ref)
    mine = splits(out / 'builtin_0D.json', dict(enumerate(names)))
    for cap in names:
        assert abs(ref[cap] - mine[cap]) < 1.0, (cap, ref[cap], mine[cap])
