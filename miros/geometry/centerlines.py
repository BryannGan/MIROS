"""
Centerlines of a vessel surface without vmtk or SimVascular.

Algorithm (Antiga & Steinman 2004, the same idea vmtk implements):

1. Voronoi diagram of the closed surface's vertices. Voronoi vertices that
   lie inside the surface approximate the medial axis; each one is the
   centre of a sphere touching the surface, and its distance to the nearest
   surface vertex is that sphere's radius.
2. Shortest paths on the Voronoi graph from the inlet to every outlet with
   edge cost = length / radius^p, so paths run through the widest part of
   the lumen.
3. All paths come from one source, so their union is a tree with exact
   shared prefixes. The tree is smoothed, resampled tract by tract, and its
   radii are re-measured against the surface.

The result is a CenterlineTree; miros.geometry.centerline_tree turns it
into the annotated polydata the reduced-order model builder reads.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import numpy as np
import vtk
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import Voronoi, cKDTree
from vtk.util.numpy_support import vtk_to_numpy as v2n

from .caps import Cap, close_surface, inlet_cap, outlet_caps, triangulate_and_clean


@dataclass
class Tract:
    """A chain of tree nodes between two of: the inlet, a split node, an outlet."""
    nodes: np.ndarray                 # node ids, upstream -> downstream
    parent: Optional[int] = None      # index of the parent tract
    children: List[int] = field(default_factory=list)
    outlets: List[int] = field(default_factory=list)   # outlet indices downstream of this tract
    terminal_outlet: Optional[int] = None              # outlet index if this tract ends at an outlet


@dataclass
class CenterlineTree:
    points: np.ndarray                # (N, 3)
    radius: np.ndarray                # (N,) maximal inscribed sphere radius
    tracts: List[Tract]
    root: int                         # index of the root tract (starts at the inlet)
    inlet_name: str
    outlet_names: List[str]           # outlet j <-> Tract.terminal_outlet == j

    def tract_sequence(self, outlet: int) -> List[int]:
        """Tract indices from the root to the tract ending at `outlet`."""
        t = [i for i, tr in enumerate(self.tracts) if tr.terminal_outlet == outlet][0]
        seq = [t]
        while self.tracts[seq[-1]].parent is not None:
            seq.append(self.tracts[seq[-1]].parent)
        return seq[::-1]

    def arc_length(self, tract: int) -> np.ndarray:
        p = self.points[self.tracts[tract].nodes]
        return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])


# ----------------------------------------------------------------------------
# step 1: medial approximation

def _surface_points_and_normals(closed: vtk.vtkPolyData):
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(closed)
    normals.ComputePointNormalsOn()
    normals.ComputeCellNormalsOff()
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.SplittingOff()
    normals.Update()
    out = normals.GetOutput()
    pts = v2n(out.GetPoints().GetData()).astype(np.float64)
    nrm = v2n(out.GetPointData().GetNormals()).astype(np.float64)
    return pts, nrm


def _voronoi_medial(points: np.ndarray, normals: np.ndarray, r_max: float, r_min: float, log):
    """
    Voronoi vertices inside the surface with their inscribed radii, and the
    Voronoi graph edges between them.

    Returns (vertices (M,3), radii (M,), edges (E,2) int)
    """
    log("  Voronoi diagram of %d surface points ..." % len(points))
    vor = Voronoi(points)
    V = vor.vertices
    tree = cKDTree(points)
    r, nn = tree.query(V)                       # radius = distance to nearest generator

    # inside test: on the inner side of the nearest surface point's outward normal,
    # and with a radius a real lumen can have
    inward = np.einsum('ij,ij->i', V - points[nn], normals[nn]) < 0
    keep = inward & (r <= r_max) & (r >= r_min)
    log("  %d Voronoi vertices, %d inside the lumen after pruning" % (len(V), keep.sum()))

    # ridge polygons -> edges between kept vertices
    keep_idx = np.full(len(V), -1, dtype=np.int64)
    keep_idx[keep] = np.arange(keep.sum())
    a, b = [], []
    for ridge in vor.ridge_vertices:
        n = len(ridge)
        for i in range(n):
            u, w = ridge[i], ridge[(i + 1) % n]
            if u >= 0 and w >= 0 and keep[u] and keep[w]:
                a.append(keep_idx[u]); b.append(keep_idx[w])
    edges = np.unique(np.sort(np.array([a, b], dtype=np.int64).T, axis=1), axis=0)
    return V[keep], r[keep], edges


def _seed_vertex(V, r, cap: Cap, tree: cKDTree) -> int:
    """Widest medial vertex within one radius of the cap centroid (inward-shifted)."""
    target = cap.centroid - 0.5 * cap.radius * cap.normal
    cand = tree.query_ball_point(target, cap.radius)
    if not cand:
        return int(tree.query(target)[1])
    cand = np.asarray(cand)
    return int(cand[np.argmax(r[cand])])


# ----------------------------------------------------------------------------
# step 2/3: paths -> tree

def _paths_to_tree(paths: Sequence[Sequence[int]], V, r, caps_in_order: Sequence[Cap], inlet: Cap):
    """
    Build node arrays and tracts from Voronoi-vertex paths (all starting at
    the same source). Adds the inlet centroid as the root node and each
    outlet centroid as the leaf node of its path.
    """
    used = sorted({v for p in paths for v in p})
    vid = {v: i for i, v in enumerate(used)}
    n_out = len(paths)
    N = len(used) + 1 + n_out
    points = np.zeros((N, 3)); radius = np.zeros(N)
    points[:len(used)] = V[used]; radius[:len(used)] = r[used]
    INLET = len(used)
    points[INLET] = inlet.centroid; radius[INLET] = inlet.radius
    leaf = {}
    for j, cap in enumerate(caps_in_order):
        leaf[j] = INLET + 1 + j
        points[leaf[j]] = cap.centroid; radius[leaf[j]] = cap.radius

    children = {i: [] for i in range(N)}
    parent = np.full(N, -1, dtype=np.int64)
    leaf_of = {}
    for j, p in enumerate(paths):
        seq = [INLET] + [vid[v] for v in p] + [leaf[j]]
        for a, b in zip(seq[:-1], seq[1:]):
            if parent[b] == -1:
                parent[b] = a
                children[a].append(b)
            elif parent[b] != a:
                raise RuntimeError("centerline paths do not form a tree (node %d has two parents)" % b)
        leaf_of[leaf[j]] = j

    # tracts: walk from the inlet, cut at nodes with >= 2 children
    tracts: List[Tract] = []

    def walk(start_parent_tract, first, second):
        nodes = [first, second]
        cur = second
        while len(children[cur]) == 1 and cur not in leaf_of:
            cur = children[cur][0]
            nodes.append(cur)
        t = Tract(nodes=np.array(nodes, dtype=np.int64), parent=start_parent_tract)
        idx = len(tracts)
        tracts.append(t)
        if cur in leaf_of:
            t.terminal_outlet = leaf_of[cur]
            t.outlets = [leaf_of[cur]]
        else:
            for ch in children[cur]:
                c = walk(idx, cur, ch)
                t.children.append(c)
                t.outlets += tracts[c].outlets
        return idx

    if len(children[INLET]) != 1:
        raise RuntimeError("inlet must start exactly one path")
    root = walk(None, INLET, children[INLET][0])
    return CenterlineTree(points=points, radius=radius, tracts=tracts, root=root,
                          inlet_name=inlet.name, outlet_names=[c.name for c in caps_in_order])


def _tree_edges(tree: CenterlineTree):
    e = []
    for t in tree.tracts:
        e.append(np.stack([t.nodes[:-1], t.nodes[1:]], axis=1))
    return np.concatenate(e, axis=0)


def _smooth_tree(tree: CenterlineTree, iterations: int, factor: float):
    """Laplacian smoothing of positions and radii over the tree graph; inlet and outlets fixed."""
    N = len(tree.points)
    edges = _tree_edges(tree)
    deg = np.bincount(edges.ravel(), minlength=N)
    fixed = deg == 1
    P = tree.points.copy(); R = tree.radius.copy()
    for _ in range(iterations):
        sP = np.zeros_like(P); sR = np.zeros_like(R)
        np.add.at(sP, edges[:, 0], P[edges[:, 1]]); np.add.at(sP, edges[:, 1], P[edges[:, 0]])
        np.add.at(sR, edges[:, 0], R[edges[:, 1]]); np.add.at(sR, edges[:, 1], R[edges[:, 0]])
        mP = sP / np.maximum(deg, 1)[:, None]; mR = sR / np.maximum(deg, 1)
        P[~fixed] = (1 - factor) * P[~fixed] + factor * mP[~fixed]
        R[~fixed] = (1 - factor) * R[~fixed] + factor * mR[~fixed]
    tree.points = P; tree.radius = R


def _resample_tree(tree: CenterlineTree, spacing: float, min_points: int = 4) -> CenterlineTree:
    """Resample every tract at `spacing`; shared split nodes stay shared."""
    new_pts, new_r = [], []
    node_map = {}          # old node id -> new id, for shared endpoints

    def add(p, r):
        new_pts.append(p); new_r.append(r)
        return len(new_pts) - 1

    new_tracts = []
    for t in tree.tracts:
        P = tree.points[t.nodes]; R = tree.radius[t.nodes]
        s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
        L = s[-1]
        n = max(min_points, int(round(L / spacing)) + 1)
        ss = np.linspace(0.0, L, n)
        Pn = np.stack([np.interp(ss, s, P[:, k]) for k in range(3)], axis=1)
        Rn = np.interp(ss, s, R)
        ids = []
        first, last = int(t.nodes[0]), int(t.nodes[-1])
        ids.append(node_map[first] if first in node_map else node_map.setdefault(first, add(Pn[0], Rn[0])))
        for k in range(1, n - 1):
            ids.append(add(Pn[k], Rn[k]))
        ids.append(node_map[last] if last in node_map else node_map.setdefault(last, add(Pn[-1], Rn[-1])))
        new_tracts.append(Tract(nodes=np.array(ids, dtype=np.int64), parent=t.parent, children=list(t.children),
                                outlets=list(t.outlets), terminal_outlet=t.terminal_outlet))
    return CenterlineTree(points=np.array(new_pts), radius=np.array(new_r), tracts=new_tracts,
                          root=tree.root, inlet_name=tree.inlet_name, outlet_names=list(tree.outlet_names))


def _measure_radius(tree: CenterlineTree, wall: vtk.vtkPolyData):
    """
    Replace radii by the exact distance from each point to the vessel WALL
    (the open surface). Measuring against the closed surface would make the
    radius collapse next to the caps.
    """
    dist = vtk.vtkImplicitPolyDataDistance()
    dist.SetInput(wall)
    r = np.array([abs(dist.EvaluateFunction(p)) for p in tree.points])
    # keep cap radii at the fixed endpoints (distance to a cap is 0 there)
    edges = _tree_edges(tree)
    deg = np.bincount(edges.ravel(), minlength=len(r))
    r[deg == 1] = tree.radius[deg == 1]
    tree.radius = r


# ----------------------------------------------------------------------------
# public entry

def compute_centerlines(surface: vtk.vtkPolyData, caps: Sequence[Cap],
                        spacing: Optional[float] = None, cost_exponent: float = 1.0,
                        smooth_iterations: int = 40, smooth_factor: float = 0.3,
                        prune_radius_ratio: float = 0.05, verbose: bool = True) -> CenterlineTree:
    """
    Compute centerlines from the inlet cap to every outlet cap.

    surface: the OPEN clipped surface (caps are added internally).
    caps: from miros.geometry.caps.make_caps; exactly one must be the inlet.
    spacing: resampling distance along tracts (default 0.1 * median radius).
    cost_exponent: p in cost = length / radius^p (1 = vmtk default).
    """
    log = print if verbose else (lambda *a, **k: None)
    inlet = inlet_cap(caps)
    outs = outlet_caps(caps)
    if not outs:
        raise ValueError("no outlet caps")

    closed = close_surface(surface, caps)
    pts, nrm = _surface_points_and_normals(closed)

    r_max = 3.0 * max(c.radius for c in caps)
    r_min = prune_radius_ratio * np.median([c.radius for c in caps])
    V, r, edges = _voronoi_medial(pts, nrm, r_max, r_min, log)

    # graph with cost = length / mean radius^p
    length = np.linalg.norm(V[edges[:, 0]] - V[edges[:, 1]], axis=1)
    rmean = 0.5 * (r[edges[:, 0]] + r[edges[:, 1]])
    w = length / np.power(rmean, cost_exponent)
    M = len(V)
    G = coo_matrix((np.concatenate([w, w]),
                    (np.concatenate([edges[:, 0], edges[:, 1]]), np.concatenate([edges[:, 1], edges[:, 0]]))),
                   shape=(M, M)).tocsr()

    vtree = cKDTree(V)
    source = _seed_vertex(V, r, inlet, vtree)
    targets = [_seed_vertex(V, r, c, vtree) for c in outs]
    log("  shortest paths from %s to %d outlets ..." % (inlet.name, len(outs)))
    dist, pred = dijkstra(G, directed=False, indices=source, return_predecessors=True)
    paths = []
    for c, t in zip(outs, targets):
        if not np.isfinite(dist[t]):
            raise RuntimeError("outlet %s is not reachable from the inlet through the lumen; "
                               "check that the surface is watertight between them" % c.name)
        p = [t]
        while p[-1] != source:
            p.append(pred[p[-1]])
        paths.append(p[::-1])

    tree = _paths_to_tree(paths, V, r, outs, inlet)
    log("  raw tree: %d nodes, %d tracts" % (len(tree.points), len(tree.tracts)))

    _smooth_tree(tree, smooth_iterations, smooth_factor)
    if spacing is None:
        spacing = 0.1 * float(np.median(tree.radius))
    tree = _resample_tree(tree, spacing)
    _measure_radius(tree, triangulate_and_clean(surface))
    log("  resampled at %.4f: %d nodes, %d tracts" % (spacing, len(tree.points), len(tree.tracts)))
    return tree
