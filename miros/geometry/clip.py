"""
Deterministic outlet clipping from cut planes (the `model.outlets` list in
case.yaml). Each plane removes the distal half-ball of radius
`extent * radius` around its origin, so a cut can only remove the local
vessel end and never a neighbouring vessel. The largest connected piece
is kept.

    outlets:
      - {name: aorta_in, origin: [x, y, z], normal: [nx, ny, nz], radius: 1.1, inlet: true}

`normal` points OUT of the vessel (toward the piece to discard).
"""
from typing import Dict, List, Sequence

import numpy as np
import vtk


def clip_with_planes(surface: vtk.vtkPolyData, planes: Sequence[Dict], extent: float = 2.0,
                     max_share: float = 0.35) -> vtk.vtkPolyData:
    """
    Open each vessel end named by a plane, and nothing else.

    A plane alone would slice every vessel that happens to cross it, and a
    plane limited by a ball still cuts through folds of a tortuous aorta
    (one cut on a real CT aorta opened thirteen holes). So each cut takes
    only the cells on the discard side of the plane that are *connected to
    that vessel end*: the piece the plane's normal points at. Everything
    else the plane passes through keeps its wall, and the cut leaves
    exactly one new opening.

    A vessel end is a small piece: a cut that would take more than
    `max_share` of the model from either side is not at an end at all, and
    is refused with a message naming it rather than eating the model. A
    normal pointing the wrong way is corrected instead of being obeyed.
    All the cuts are worked out against the surface as it came in, and the
    cells they claim are removed in one pass at the end.
    """
    import pyvista as pv

    base = pv.wrap(surface).triangulate().clean()
    base.cell_data['_miros_cell'] = np.arange(base.n_cells, dtype=np.int64)
    centers = base.cell_centers().points
    skipped: List[str] = []
    refused: List[str] = []
    remove_all: List[np.ndarray] = []
    applied: List[tuple] = []
    for k, p in enumerate(planes):
        o = np.asarray(p['origin'], dtype=float)
        n = np.asarray(p['normal'], dtype=float)
        n = n / max(np.linalg.norm(n), 1e-12)
        r = float(p['radius'])
        name = p.get('name', '') or 'cut %d' % k

        def piece(direction):
            """
            The connected piece of surface on the `direction` side of the
            plane that the cut points at: the vessel end, if this is one.

            The whole side is searched, not a ball around the cut, because
            a thin branch next to a big vessel has both within a couple of
            its own radii, and only connectivity tells them apart.
            """
            side = np.where((centers - o) @ direction > 0.0)[0]
            if len(side) == 0:
                return None
            sub = base.extract_cells(side).extract_surface(algorithm='dataset_surface')
            near = sub.connectivity('closest', closest_point=o + 0.25 * r * direction)
            ids = np.unique(np.asarray(near.cell_data['_miros_cell'], dtype=np.int64))
            return ids if len(ids) else None

        remove = piece(n)
        if remove is None or len(remove) > max_share * base.n_cells:
            other = piece(-n)                        # a normal pointing the wrong way is a common mistake
            if other is not None and len(other) <= max_share * base.n_cells:
                p['normal'] = [float(v) for v in -n]
                n, remove = -n, other
        if remove is None:
            skipped.append(name)
            continue
        if len(remove) > max_share * base.n_cells:
            refused.append('%s (%.0f%% of the model)' % (name, 100.0 * len(remove) / base.n_cells))
            continue                                  # not at a vessel end: leave the wall alone
        remove_all.append(remove)
        applied.append((o, n, r))

    if not applied:
        raise ValueError("none of the %d cuts opened a vessel end" % len(planes))
    gone = np.unique(np.concatenate(remove_all))
    keep = np.setdiff1d(np.arange(base.n_cells), gone)
    if len(keep) == 0:
        raise ValueError("the cuts removed the whole surface")
    out = base.extract_cells(keep).extract_surface(algorithm='dataset_surface').clean()
    out.cell_data.pop('_miros_cell', None)
    out.point_data['_miros_point'] = np.arange(out.n_points, dtype=np.int64)   # numbering after the clean
    for o, n, r in applied:
        _flatten_rim(out, o, n, 3.0 * r)
    out.point_data.pop('_miros_point', None)
    if skipped or refused:
        from ..ui import console
        if skipped:
            console.warn('nothing left to cut for %s (an earlier cut had already opened that end)'
                         % ', '.join(skipped))
        if refused:
            console.warn('not cut, because the vessel keeps going past the plane in both directions '
                         '(a cut mid-vessel, not at an end): %s. Move or switch those cuts off on the '
                         'Outlets step.' % ', '.join(refused))
    conn = vtk.vtkPolyDataConnectivityFilter()
    conn.SetInputData(out)
    conn.SetExtractionModeToLargestRegion()
    conn.Update()
    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(conn.GetOutputPort())
    clean.Update()
    return clean.GetOutput()


def _flatten_rim(surf, origin, normal, reach: float) -> None:
    """
    Whole cells are removed, so a fresh opening is jagged by one cell.
    Project the rim points near the cut onto the plane: the cap becomes
    flat, and no point moves further than the mesh is coarse.
    """
    edges = surf.extract_feature_edges(boundary_edges=True, feature_edges=False,
                                       manifold_edges=False, non_manifold_edges=False)
    if edges.n_points == 0 or '_miros_point' not in edges.point_data:
        return
    ids = np.asarray(edges.point_data['_miros_point'], dtype=np.int64)
    pts = surf.points
    near = ids[np.linalg.norm(pts[ids] - origin, axis=1) < reach]
    if len(near) == 0:
        return
    d = (pts[near] - origin) @ normal
    pts[near] = pts[near] - np.outer(d, normal)
    surf.points = pts


def plane_names_for_caps(caps, planes: Sequence[Dict]) -> List[str]:
    """
    Name each cap (in the given order) after the plane that cut it.

    A cut plane usually makes exactly one cap, but not always: a plane can
    open a vessel wide enough to expose a neighbour, and two planes in the
    same vessel end can leave one cap between them. So the closest
    cap-plane pairs are matched first, and any cap left over gets its own
    name instead of stealing one.
    """
    origins = np.array([np.asarray(p['origin'], float) for p in planes]) if planes else np.zeros((0, 3))
    d = np.array([[np.linalg.norm(o - c.centroid) for o in origins] for c in caps]) if len(origins) else None
    names: List[str] = [''] * len(caps)
    if d is not None and d.size:
        order = np.dstack(np.unravel_index(np.argsort(d, axis=None), d.shape))[0]
        taken_cap, taken_plane = set(), set()
        for i, j in order:                       # closest pairs first, one plane per cap
            if i in taken_cap or j in taken_plane:
                continue
            names[i] = planes[j].get('name') or ('cap_%d' % (j + 1))
            taken_cap.add(i)
            taken_plane.add(j)
    used = {n for n in names if n}
    spare = 1
    for i, n in enumerate(names):
        while not n:                             # a cap no plane accounts for
            candidate = 'cap_x%d' % spare
            spare += 1
            if candidate not in used:
                names[i] = n = candidate
                used.add(candidate)
    return names
