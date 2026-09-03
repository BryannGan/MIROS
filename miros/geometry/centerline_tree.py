"""
Annotate a CenterlineTree in the layout the reduced-order model builder
(miros.rom.mesh, vendored from SimVascular) reads.

The convention, reverse-engineered from sv.vmtk.centerlines output and from
what mesh.py consumes:

* points are emitted centerline by centerline (inlet -> outlet j, in outlet
  order); tracts shared with an earlier centerline are emitted once;
* every 2-point line cell points downstream;
* around each split a "bifurcation region" is blanked: BranchId = -1 and
  BifurcationId >= 0 there; elsewhere BranchId >= 0 and BifurcationId = -1;
* BranchId 0 is the inlet trunk and point 0 is the inlet;
* the point just before a branch's first point lies in its upstream
  bifurcation region (mesh.py reads it to find the junction);
* Path restarts at 0 at the first point of each branch;
* CenterlineId[:, j] == 1 on every point of centerline j;
* CenterlineSectionArea / CenterlineSectionNormal are the cross-section
  area and unit tangent; GlobalNodeId is the point index.
"""
from typing import Sequence

import numpy as np
import pyvista as pv
import vtk
from scipy.spatial import cKDTree
from vtk.util.numpy_support import numpy_to_vtk as n2v
from vtk.util.numpy_support import vtk_to_numpy as v2n

from .caps import _polygon_area_centroid_normal
from .centerlines import CenterlineTree, _tree_edges


# ----------------------------------------------------------------------------
# blanking

def _blank_regions(tree: CenterlineTree, min_keep: int = 3) -> np.ndarray:
    """Boolean per node: inside a bifurcation region."""
    P, R = tree.points, tree.radius
    blank = np.zeros(len(P), dtype=bool)

    for ti, t in enumerate(tree.tracts):
        if not t.children:
            continue
        S = int(t.nodes[-1])
        rS = R[S]
        blank[S] = True

        # upstream along this tract while inside the split sphere
        lo = min_keep if ti == tree.root else 1
        for k in range(len(t.nodes) - 2, lo - 1, -1):
            if np.linalg.norm(P[t.nodes[k]] - P[S]) < rS:
                blank[t.nodes[k]] = True
            else:
                break

        # downstream on each child while inside the split sphere or a sibling's tube
        sib_trees = {}
        for c in t.children:
            cn = tree.tracts[c].nodes[1:]
            sib_trees[c] = (cKDTree(P[cn]), R[cn])
        for c in t.children:
            ct = tree.tracts[c]
            nodes = ct.nodes[1:]
            hi = len(nodes) - min_keep if ct.terminal_outlet is not None else len(nodes) - 1
            hi = max(hi, 1)
            for k, n in enumerate(nodes):
                if k >= hi:
                    break
                inside = k == 0 or np.linalg.norm(P[n] - P[S]) < rS
                if not inside:
                    for s in t.children:
                        if s == c:
                            continue
                        kd, rs = sib_trees[s]
                        d, i = kd.query(P[n])
                        if d < rs[i]:
                            inside = True
                            break
                if inside:
                    blank[n] = True
                else:
                    break
    return blank


def _regions(tree: CenterlineTree, blank: np.ndarray) -> np.ndarray:
    """Connected components of blanked nodes over tree edges; -1 elsewhere."""
    N = len(blank)
    comp = np.full(N, -1, dtype=np.int64)
    edges = _tree_edges(tree)
    adj = [[] for _ in range(N)]
    for a, b in edges:
        if blank[a] and blank[b]:
            adj[a].append(b); adj[b].append(a)
    c = 0
    for n in range(N):
        if blank[n] and comp[n] == -1:
            stack = [n]; comp[n] = c
            while stack:
                u = stack.pop()
                for v in adj[u]:
                    if comp[v] == -1:
                        comp[v] = c; stack.append(v)
            c += 1
    return comp


# ----------------------------------------------------------------------------
# sections

def _point_in_polygon(x: np.ndarray, y: np.ndarray) -> bool:
    """Is the origin inside the polygon with vertices (x, y)? (crossing number)"""
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    cross = (y > 0) != (y2 > 0)
    with np.errstate(divide='ignore', invalid='ignore'):
        xint = x + (0.0 - y) * (x2 - x) / (y2 - y)
    return int(np.count_nonzero(cross & (xint > 0))) % 2 == 1


class _SectionCutter:
    """
    Cross-section area of the closed surface at a point: cut with the plane
    through the point normal to the tangent, and take the smallest cut loop
    that contains the point (the vessel's own lumen, not a neighbour's).
    """

    def __init__(self, closed: vtk.vtkPolyData):
        self.plane = vtk.vtkPlane()
        self.cutter = vtk.vtkCutter()
        self.cutter.SetInputData(closed)
        self.cutter.SetCutFunction(self.plane)
        self.strip = vtk.vtkStripper()
        self.strip.SetInputConnection(self.cutter.GetOutputPort())
        self.strip.JoinContiguousSegmentsOn()
        self.strip.SetMaximumLength(closed.GetNumberOfPoints() or 1)    # default 1000 splits a fine cut loop

    def area(self, point, normal, radius):
        n = normal / max(np.linalg.norm(normal), 1e-12)
        self.plane.SetOrigin(*point)
        self.plane.SetNormal(*n)
        self.strip.Update()
        out = self.strip.GetOutput()
        if out.GetNumberOfPoints() == 0 or out.GetNumberOfLines() == 0:
            return None
        pts = v2n(out.GetPoints().GetData())
        # in-plane basis
        u = np.cross(n, [1.0, 0.0, 0.0])
        if np.linalg.norm(u) < 1e-6:
            u = np.cross(n, [0.0, 1.0, 0.0])
        u /= np.linalg.norm(u)
        v = np.cross(n, u)

        containing, others = [], []
        ids = vtk.vtkIdList()
        lines = out.GetLines()
        lines.InitTraversal()
        while lines.GetNextCell(ids):
            idx = [ids.GetId(i) for i in range(ids.GetNumberOfIds())]
            if len(idx) > 1 and idx[0] == idx[-1]:
                idx = idx[:-1]
            if len(idx) < 3:
                continue
            loop = pts[idx]
            q = loop - point
            a, c, _ = _polygon_area_centroid_normal(loop)
            if a <= 0:
                continue
            if _point_in_polygon(q @ u, q @ v):
                containing.append(a)
            else:
                others.append((np.linalg.norm(c - point), a))
        if containing:
            return min(containing)
        if others:
            d, a = min(others)
            if d < 1.5 * radius:
                return a
        return None


# ----------------------------------------------------------------------------
# emission

def annotate(tree: CenterlineTree, closed: vtk.vtkPolyData, compute_sections: bool = True,
             max_area_ratio: float = 3.0, verbose: bool = True) -> vtk.vtkPolyData:
    """
    Build the annotated centerline polydata from a CenterlineTree.

    max_area_ratio: upper bound on CenterlineSectionArea / (pi r^2).
    """
    log = print if verbose else (lambda *a, **k: None)
    P, R = tree.points, tree.radius
    N = len(P)
    n_out = len(tree.outlet_names)

    blank = _blank_regions(tree)
    comp = _regions(tree, blank)

    # tangent per node along its tract (children overwrite the split node's tangent
    # only if it had none; the parent tract sets it first)
    tangent = np.zeros((N, 3))
    have = np.zeros(N, dtype=bool)
    for t in tree.tracts:
        pts = P[t.nodes]
        d = np.gradient(pts, axis=0) if len(pts) > 2 else np.diff(pts, axis=0).repeat(2, axis=0)
        d /= np.maximum(np.linalg.norm(d, axis=1), 1e-12)[:, None]
        for k, n in enumerate(t.nodes):
            if not have[n]:
                tangent[n] = d[k]; have[n] = True

    # global arc length from the inlet, per node
    s_global = np.zeros(N)
    order_tracts = []
    stack = [tree.root]
    while stack:
        ti = stack.pop()
        order_tracts.append(ti)
        stack.extend(tree.tracts[ti].children)
    for ti in order_tracts:
        t = tree.tracts[ti]
        s = tree.arc_length(ti)
        s_global[t.nodes] = s_global[t.nodes[0]] + s

    # centerline membership
    cid = np.zeros((N, n_out), dtype=np.int32)
    for t in tree.tracts:
        for j in t.outlets:
            cid[t.nodes, j] = 1

    # emission order
    gid = np.full(N, -1, dtype=np.int64)
    order = []
    cells = []
    emitted = set()
    tract_first_branch_node = {}
    for j in range(n_out):
        for ti in tree.tract_sequence(j):
            if ti in emitted:
                continue
            emitted.add(ti)
            t = tree.tracts[ti]
            nodes = list(t.nodes) if ti == tree.root else list(t.nodes[1:])
            prev = None if ti == tree.root else int(t.nodes[0])
            for n in nodes:
                gid[n] = len(order)
                order.append(int(n))
                if prev is not None:
                    cells.append((gid[prev], gid[n]))
                prev = n
    order = np.array(order, dtype=np.int64)
    assert len(order) == N, "not every node was emitted"

    # ids in emission order
    branch_id = np.full(N, -1, dtype=np.int64)
    bif_id = np.full(N, -1, dtype=np.int64)
    next_branch, next_bif = 0, 0
    tract_branch = {}
    comp_bif = {}
    node_tract = np.full(N, -1, dtype=np.int64)
    for ti, t in enumerate(tree.tracts):
        for n in (t.nodes if ti == tree.root else t.nodes[1:]):
            node_tract[n] = ti
    for n in order:
        if blank[n]:
            if comp[n] not in comp_bif:
                comp_bif[comp[n]] = next_bif; next_bif += 1
            bif_id[n] = comp_bif[comp[n]]
        else:
            ti = node_tract[n]
            if ti not in tract_branch:
                tract_branch[ti] = next_branch; next_branch += 1
                tract_first_branch_node[ti] = n
            branch_id[n] = tract_branch[ti]

    # Path: from the first point of the branch; global arc length in regions
    path = s_global.copy()
    for ti, n0 in tract_first_branch_node.items():
        m = (branch_id == tract_branch[ti])
        path[m] = s_global[m] - s_global[n0]

    # sections: measured on branch points, then median-filtered along each branch
    # and bounded below by the inscribed circle (a lumen section always contains
    # the great circle of its maximal inscribed sphere) and above to keep sections
    # that cut into a neighbouring vessel near a junction from dominating.
    area = np.pi * R ** 2
    if compute_sections:
        from scipy.ndimage import median_filter
        log("  cross-sections at %d branch points ..." % int((~blank).sum()))
        cutter = _SectionCutter(closed)
        measured = np.full(N, np.nan)
        for n in np.where(~blank)[0]:
            a = cutter.area(P[n], tangent[n], R[n])
            if a is not None:
                measured[n] = a
        for ti, t in enumerate(tree.tracts):
            nodes = np.array([n for n in t.nodes if not blank[n]])
            if len(nodes) == 0:
                continue
            a = measured[nodes]
            circle = np.pi * R[nodes] ** 2
            a = np.where(np.isnan(a), circle, a)
            if len(a) >= 5:
                a = median_filter(a, size=5, mode='nearest')
            area[nodes] = np.clip(a, circle, max_area_ratio * circle)

    # sanity checks mirroring mesh.py's assumptions
    root_first = tree.tracts[tree.root].nodes[0]
    assert gid[root_first] == 0 and not blank[root_first], "inlet point must be point 0 and unblanked"
    for t in tree.tracts:
        if t.terminal_outlet is not None:
            assert not blank[t.nodes[-1]], "outlet %s ends inside a bifurcation region; the outlet is too close to a split" % tree.outlet_names[t.terminal_outlet]
    log("  %d branches, %d bifurcation regions" % (next_branch, next_bif))

    # polydata
    pd = vtk.vtkPolyData()
    vpts = vtk.vtkPoints()
    vpts.SetData(n2v(np.ascontiguousarray(P[order], dtype=np.float64), deep=True))
    pd.SetPoints(vpts)
    ca = vtk.vtkCellArray()
    for a, b in cells:
        ca.InsertNextCell(2); ca.InsertCellPoint(int(a)); ca.InsertCellPoint(int(b))
    pd.SetLines(ca)

    def add(name, arr, dtype):
        a = n2v(np.ascontiguousarray(arr[order], dtype=dtype), deep=True)
        a.SetName(name)
        pd.GetPointData().AddArray(a)

    add('BranchId', branch_id, np.int64)
    add('BifurcationId', bif_id, np.int64)
    add('CenterlineId', cid, np.int32)
    add('Path', path, np.float64)
    add('MaximumInscribedSphereRadius', R, np.float64)
    add('CenterlineSectionArea', area, np.float64)
    add('CenterlineSectionNormal', tangent, np.float64)
    add('GlobalNodeId', np.arange(N), np.int32)
    return pd


def write_outlet_names(names: Sequence[str], path) -> None:
    with open(path, 'w', newline='\n') as f:
        for n in names:
            f.write(n + '\n')
