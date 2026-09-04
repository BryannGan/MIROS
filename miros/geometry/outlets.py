"""
Propose outlet cut planes for a closed SeqSeg surface, so its bulbous
vessel ends can be clipped open automatically.

Two sources:

* `propose_from_closed_surface` — from the surface alone (the normal
  case): the Voronoi medial graph is rooted at the widest medial vertex
  and a vessel end is a vertex that is the farthest point (largest
  geodesic distance) within a few radii around it. The end nearest the
  seed becomes the inlet.
* `propose_outlet_planes` — from a tracked centerline with `CenterlineId`
  columns and radii, when one is available.

Each end is cut `back_off` local radii inside the tip, with the plane
normal pointing toward the tip (the side to discard).
"""
from typing import Dict, List

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy as v2n


def propose_from_closed_surface(surface: vtk.vtkPolyData, seed_point, back_off: float = 2.5,
                                min_branch_radii: float = 4.0, max_ends: int = 40,
                                min_separation: float = 1.5, min_radius_frac: float = 0.05,
                                keep: int = 20, verbose: bool = False) -> List[Dict]:
    """
    Returns [{'name', 'origin', 'normal', 'radius', 'inlet'} ...] for a
    CLOSED vessel surface; the first plane is the inlet (nearest the seed).

    Farthest-point growth of a tree over the medial graph: start at the
    widest medial vertex, repeatedly take the vertex farthest from the tree
    in radius-normalized geodesic distance, add its path to the tree, and
    stop when the farthest vertex is closer than `min_branch_radii` radii.
    Every accepted vertex is the tip of a branch at least that long; a
    bump on a wall never is.
    """
    import pyvista as pv
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components, dijkstra
    from .centerlines import _surface_points_and_normals, _voronoi_medial

    log = print if verbose else (lambda *a, **k: None)
    closed = pv.wrap(surface).triangulate().clean()
    if closed.n_points > 80000:                             # SeqSeg surfaces are oversampled for this purpose
        closed = closed.decimate(1.0 - 80000.0 / closed.n_points).clean()
    pts, nrm = _surface_points_and_normals(closed)
    edge = float(np.median(closed.compute_cell_sizes(length=False, volume=False)['Area']) ** 0.5)
    b = closed.bounds
    r_max = 0.25 * max(b[1] - b[0], b[3] - b[2], b[5] - b[4])
    # prune only true near-surface noise: thin vessels (renals, iliacs) must stay connected
    V, R, E = _voronoi_medial(pts, nrm, r_max, 0.7 * edge, log)
    if len(V) == 0 or len(E) == 0:
        return []
    length = np.linalg.norm(V[E[:, 0]] - V[E[:, 1]], axis=1)
    w = length / (0.5 * (R[E[:, 0]] + R[E[:, 1]]))            # cost in local radii
    M = len(V)
    G = coo_matrix((np.r_[w, w], (np.r_[E[:, 0], E[:, 1]], np.r_[E[:, 1], E[:, 0]])), shape=(M, M)).tocsr()
    n_comp, labels = connected_components(G, directed=False)
    main = np.argmax(np.bincount(labels))
    root = int(np.argmax(np.where(labels == main, R, -1.0)))

    tree_nodes = [root]
    in_tree = np.zeros(M, dtype=bool)
    in_tree[root] = True
    tips: List[int] = []
    paths: Dict[int, List[int]] = {}
    for _ in range(4 * max_ends):
        if len(tips) >= max_ends:
            break
        dist, pred = dijkstra(G, directed=False, indices=tree_nodes, min_only=True, return_predecessors=True)[:2]
        dist = np.where(np.isfinite(dist), dist, -1.0)
        far = int(np.argmax(dist))
        if dist[far] < min_branch_radii:
            break
        path = [far]
        while not in_tree[path[-1]]:
            nxt = int(pred[path[-1]])
            if nxt < 0:
                break
            path.append(nxt)
        # a real branch is many of its own radii long in absolute terms; a medial spur next to
        # the wall of a wide vessel is "far" only because its own radius is tiny
        P = V[path]
        L = float(np.sum(np.linalg.norm(np.diff(P, axis=0), axis=1))) if len(path) > 1 else 0.0
        if L >= min_branch_radii * float(R[path].max()):
            tips.append(far)
            paths[far] = path
        for v in path:                       # absorbed either way, so it is never picked again
            if not in_tree[v]:
                in_tree[v] = True
                tree_nodes.append(v)
    log("  %d vessel ends" % len(tips))
    if not tips:
        return []

    def cut(tip: int):
        """
        Walk from the tip into the vessel and stop `back_off` radii in. The
        radius is measured near the tip (see `_vessel_radius`), so the cut
        cannot wander up the tree into a thicker vessel.
        """
        path = paths[tip]
        P = V[path]                                         # tip -> tree
        Rp = R[path]
        s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
        r_ref = _vessel_radius(s, Rp)
        k = int(np.searchsorted(s, back_off * r_ref))
        k = min(max(k, 1), len(P) - 2) if len(P) > 2 else 0
        origin = P[k]
        tangent = P[max(k - 3, 0)] - P[min(k + 3, len(P) - 1)]
        n = np.linalg.norm(tangent)
        return origin, (tangent / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])), r_ref

    seed = np.asarray(seed_point, dtype=float)
    inlet_tip = min(tips, key=lambda t: np.linalg.norm(V[t] - seed))
    cuts = {t: cut(t) for t in tips}
    r_big = max(c[2] for c in cuts.values())
    planes: List[Dict] = []
    used: List[Dict] = []
    for t in sorted(tips, key=lambda t: (t != inlet_tip, -cuts[t][2])):   # inlet first, then widest
        origin, normal, r_here = cuts[t]
        is_inlet = (t == inlet_tip)
        why = ''
        if not is_inlet:
            if r_here < min_radius_frac * r_big:
                why = 'thinner than %.0f%% of the widest end' % (100 * min_radius_frac)
            elif any(np.linalg.norm(np.asarray(q['origin']) - origin) < min_separation * max(r_here, q['radius'])
                     for q in used):
                why = 'same vessel end as a cut already proposed'
            elif len(used) >= keep:
                why = 'past the %d widest ends' % keep
        d = dict(name='', origin=[float(x) for x in origin], normal=[float(x) for x in normal],
                 radius=r_here, inlet=is_inlet, use=not why, skipped=why,
                 box_width=1.6 * r_here, box_length=(back_off + 1.5) * r_here)
        planes.append(d)
        if not why:
            used.append(d)
    n = 0
    for d in planes:
        if d['inlet']:
            d['name'] = 'inlet'
        else:
            n += 1
            d['name'] = 'cap_%d' % n
    log("  %d vessel ends, %d proposed as cuts" % (len(planes), len(used)))
    return planes


def _vessel_radius(s: np.ndarray, radii: np.ndarray, near: float = 3.0) -> float:
    """
    The radius of the vessel a tip belongs to.

    A medial or tracked radius collapses at a rounded tip, so the largest
    value near the tip is the honest one; and it is taken only from the
    tip's own neighbourhood, because further in the path runs into thicker
    vessels and a cut placed by that radius would sit past a junction.
    """
    r = np.asarray(radii, dtype=float)
    if r.size == 0:
        return 0.0
    r0 = float(r[:min(len(r), 5)].max())
    window = r[np.asarray(s, float) <= near * max(r0, 1e-9)]
    return float(max(window.max(), r0)) if window.size else r0


def _polylines(cl: vtk.vtkPolyData) -> List[np.ndarray]:
    """
    Ordered point-index arrays, one per path. Line cells are the truth when
    the file has them (SeqSeg writes one cell per branch, root to tip).
    Otherwise fall back to CenterlineId, which comes in two shapes: one
    column per path (SimVascular) or a single column of branch labels.
    """
    lines = cl.GetLines()
    ids = vtk.vtkIdList()
    out = []
    lines.InitTraversal()
    while lines.GetNextCell(ids):
        idx = np.array([ids.GetId(i) for i in range(ids.GetNumberOfIds())])
        if len(idx) >= 3:
            out.append(idx)
    if out:
        return out
    cid = cl.GetPointData().GetArray('CenterlineId')
    if cid is None:
        return []
    m = v2n(cid)
    if m.ndim == 2 and m.shape[1] > 1:
        return [np.where(m[:, j] > 0)[0] for j in range(m.shape[1]) if (m[:, j] > 0).sum() >= 3]
    m = m.ravel()
    return [np.where(m == label)[0] for label in np.unique(m) if (m == label).sum() >= 3]


def propose_outlet_planes(centerline: vtk.vtkPolyData, back_off: float = 2.5, include_start: bool = True,
                          min_separation: float = 1.0, seed_point=None,
                          min_branch_radii: float = 4.0) -> List[Dict]:
    """
    Cut planes from a tracked centerline (paths with radii): one at the end
    of every path, plus the start of the first path when `include_start`.
    Planes closer than `min_separation` radii to an earlier one are dropped
    (paths that end in the same vessel). With `seed_point`, the end nearest
    it is the inlet, which is what a SeqSeg tree needs: its paths all start
    at the seed, so the inlet is a tip like any other.
    """
    pts = v2n(centerline.GetPoints().GetData())
    r_arr = centerline.GetPointData().GetArray('MaximumInscribedSphereRadius')
    radius = v2n(r_arr) if r_arr is not None else None
    planes: List[Dict] = []

    def add(path: np.ndarray, from_end: bool, is_inlet: bool):
        p = pts[path[::-1]] if from_end else pts[path]     # walk from the tip inward
        rr = radius[path[::-1]] if (radius is not None and from_end) else (radius[path] if radius is not None else None)
        seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(seg)])
        r_tip = _vessel_radius(s, rr) if rr is not None else float(np.linalg.norm(p[1] - p[0]))
        k = int(np.searchsorted(s, back_off * r_tip))
        k = min(max(k, 1), len(p) - 2)
        origin = p[k]
        tangent = p[k - 1] - p[k + 1]                     # points toward the tip
        n = np.linalg.norm(tangent)
        if n < 1e-9:
            return
        normal = tangent / n
        r_here = max(float(rr[k]), r_tip) if rr is not None else r_tip
        why = ''
        if s[-1] < min_branch_radii * r_tip:
            why = 'branch shorter than %.0f of its own radii: a stub, not a vessel end' % min_branch_radii
        for q in planes:
            if not why and q.get('use', True) and \
                    np.linalg.norm(np.asarray(q['origin']) - origin) < min_separation * max(r_here, q['radius']):
                why = 'same vessel end as a cut already proposed'
                break
        planes.append(dict(name='', origin=[float(v) for v in origin], normal=[float(v) for v in normal],
                           radius=r_here, inlet=is_inlet, use=not why, skipped=why,
                           box_width=1.6 * r_here, box_length=(back_off + 1.5) * r_here))

    paths = _polylines(centerline)
    if not paths:
        return planes
    if include_start and seed_point is None:
        add(paths[0], from_end=False, is_inlet=True)
    for path in paths:
        add(path, from_end=True, is_inlet=False)
    if seed_point is not None and planes:
        seed = np.asarray(seed_point, dtype=float)
        j = int(np.argmin([np.linalg.norm(np.asarray(q['origin']) - seed) for q in planes]))
        planes[j]['inlet'] = True
    planes.sort(key=lambda d: (not d['inlet'], -d['radius']))
    n = 0
    for d in planes:
        if d['inlet']:
            d['name'] = 'inlet'
        else:
            n += 1
            d['name'] = 'cap_%d' % n
    return planes
