import numpy as np
import pytest
import pyvista as pv

from miros.geometry import caps as C


def _tube(radius=0.5, length=4.0, n=64, m=40):
    """Open cylinder along z (a vessel with two caps missing)."""
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    z = np.linspace(0, length, m)
    pts = np.array([[radius * np.cos(a), radius * np.sin(a), zz] for zz in z for a in theta])
    faces = []
    for i in range(m - 1):
        for j in range(n):
            a, b = i * n + j, i * n + (j + 1) % n
            c, d = (i + 1) * n + j, (i + 1) * n + (j + 1) % n
            faces += [3, a, b, d, 3, a, d, c]
    return pv.PolyData(pts, np.array(faces))


def test_caps_on_open_cylinder():
    tube = _tube()
    caps = C.make_caps(tube)
    assert len(caps) == 2
    assert sum(c.is_inlet for c in caps) == 1
    for c in caps:
        assert abs(c.area - np.pi * 0.5 ** 2) / (np.pi * 0.25) < 0.01
        assert abs(abs(c.normal[2]) - 1.0) < 1e-3          # normal along the axis
    # normals point outward: away from the tube centre
    centre = tube.points.mean(axis=0)
    for c in caps:
        assert np.dot(c.normal, c.centroid - centre) > 0
    closed = pv.wrap(C.close_surface(tube, caps))
    assert closed.n_open_edges == 0 and closed.is_manifold


def test_caps_naming_and_inlet_selection():
    tube = _tube()
    caps = C.make_caps(tube, names=['top', 'bottom'], inlet='bottom')
    assert [c.name for c in caps] == ['top', 'bottom']
    assert C.inlet_cap(caps).name == 'bottom'
    with pytest.raises(ValueError):
        C.make_caps(tube, inlet='nope')
    with pytest.raises(ValueError):
        C.make_caps(tube, names=['only_one'])


def test_closed_surface_has_no_caps():
    sphere = pv.Sphere()
    with pytest.raises(ValueError):
        C.make_caps(sphere)


def test_fill_small_loops_removes_single_missing_triangle():
    tube = _tube()
    faces = tube.faces.reshape(-1, 4)
    holed = pv.PolyData(tube.points, np.delete(faces, 19 * 128 + 5, axis=0).ravel())   # one interior triangle missing
    assert len(C.boundary_loops(C.triangulate_and_clean(holed))) == 3
    filled = C.fill_small_loops(holed)
    assert len(C.boundary_loops(filled)) == 2


@pytest.mark.slow
def test_caps_match_simvascular_on_test_case(surface_path, sv_reference):
    surf = C.read_polydata(surface_path)
    caps = C.make_caps(surf)
    assert len(caps) == 6
    sv = {}
    for f in sv_reference['caps'].glob('*.vtp'):
        if f.stem != 'wall':
            p = pv.read(str(f)); sv[f.stem] = (p.points.mean(axis=0), p.area)
    for c in caps:
        name = min(sv, key=lambda k: np.linalg.norm(sv[k][0] - c.centroid))
        # SimVascular centroids are means of unevenly triangulated cap meshes, not area centroids
        assert np.linalg.norm(sv[name][0] - c.centroid) < 0.2
        assert abs(c.area - sv[name][1]) / sv[name][1] < 0.01
