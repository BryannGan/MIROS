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


BOX_WIDTH = 1.6          # half-width of a cut box, in vessel radii
BOX_LENGTH = 3.0         # how far it reaches past the plane, in vessel radii


def box_of(plane: Dict):
    """
    The box a cut removes: origin, axis (out of the vessel), half-width and
    length, taking the plane's own `box_width` / `box_length` when it has
    them and a default in vessel radii otherwise.
    """
    o = np.asarray(plane['origin'], dtype=float)
    n = np.asarray(plane['normal'], dtype=float)
    n = n / max(np.linalg.norm(n), 1e-12)
    r = float(plane['radius'])
    return o, n, float(plane.get('box_width', BOX_WIDTH * r)), float(plane.get('box_length', BOX_LENGTH * r))


def _frame(n: np.ndarray):
    """Two unit vectors across the box, given its axis."""
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(helper, n)
    u /= max(np.linalg.norm(u), 1e-12)
    return u, np.cross(n, u)


def box_planes(o, n, half_width: float, length: float) -> vtk.vtkPlanes:
    """
    The six half-spaces of the cut box, as SimVascular's box trim does it:
    an implicit function for vtkClipPolyData, so the cut face is exact
    rather than following the edges of whichever triangles were in the way.
    """
    u, v = _frame(np.asarray(n, float))
    o = np.asarray(o, float)
    faces = [(o, -np.asarray(n, float)),                       # the cut face itself
             (o + length * np.asarray(n, float), np.asarray(n, float)),
             (o + half_width * u, u), (o - half_width * u, -u),
             (o + half_width * v, v), (o - half_width * v, -v)]
    points, normals = vtk.vtkPoints(), vtk.vtkDoubleArray()
    normals.SetNumberOfComponents(3)
    for p, nrm in faces:                                       # normals point out of the box
        points.InsertNextPoint(*[float(x) for x in p])
        normals.InsertNextTuple3(*[float(x) for x in nrm])
    planes = vtk.vtkPlanes()
    planes.SetPoints(points)
    planes.SetNormals(normals)
    return planes


def box_corners(o, n, half_width: float, length: float) -> np.ndarray:
    u, v = _frame(np.asarray(n, float))
    o, n = np.asarray(o, float), np.asarray(n, float)
    return np.array([o + a * half_width * u + b * half_width * v + c * length * n
                     for a in (-1, 1) for b in (-1, 1) for c in (0, 1)])


def clip_with_planes(surface: vtk.vtkPolyData, planes: Sequence[Dict], extent: float = 2.0,
                     max_share: float = 0.5) -> vtk.vtkPolyData:
    """
    Open each vessel end with a box, and touch nothing else.

    A plane cuts the whole model, and even a plane bounded by a ball slices
    through folds of a tortuous aorta: on a real CT aorta one such cut
    opened thirteen holes. A cut is a box instead, the way SimVascular's
    box trim works: six half-spaces given to vtkClipPolyData, so the cut
    face is exact and flat rather than following triangle edges. It starts
    at the plane, reaches `box_length` along the outward normal and is
    `box_width` wide, both in centimetres and both editable per cut.

    Of the wall inside the box, only the piece connected to the vessel end
    at the cut is removed; anything else the box happens to contain is
    stitched back, so a neighbouring vessel crossing the box keeps its
    wall. The box grows along the vessel until the piece it takes ends
    inside it, so a cut part way along a vessel trims it there instead of
    opening a window in its side. A cut that would take more than
    `max_share` of the model is refused with a message naming it, and a
    normal pointing the wrong way is corrected rather than obeyed.
    """
    import pyvista as pv

    out = pv.wrap(surface).triangulate().clean()
    skipped: List[str] = []
    refused: List[str] = []
    for k, p in enumerate(planes):
        o, n, half_width, length = box_of(p)
        r = float(p['radius'])
        name = p.get('name', '') or 'cut %d' % k

        def cut(direction, grown):
            """(surface with that vessel end removed, cells removed, end fits in the box)."""
            corners = box_corners(o, direction, half_width, grown)
            lo, hi = corners.min(axis=0) - 1e-6, corners.max(axis=0) + 1e-6
            pts = out.points
            near_pt = np.all((pts >= lo) & (pts <= hi), axis=1)
            tri = out.faces.reshape(-1, 4)[:, 1:]
            near = np.where(near_pt[tri].any(axis=1))[0]        # only cells the box can reach
            if len(near) == 0:
                return None, 0, False
            local = out.extract_cells(near).extract_surface(algorithm='dataset_surface')
            rest = out.extract_cells(np.setdiff1d(np.arange(out.n_cells), near)).extract_surface(
                algorithm='dataset_surface')
            clipper = vtk.vtkClipPolyData()
            clipper.SetInputData(local)
            clipper.SetClipFunction(box_planes(o, direction, half_width, grown))
            clipper.GenerateClippedOutputOn()
            clipper.InsideOutOff()
            clipper.Update()
            outside = pv.wrap(clipper.GetOutput())              # kept: beyond the box
            inside = pv.wrap(clipper.GetClippedOutput())        # candidates: within the box
            if inside.n_cells == 0:
                return None, 0, False
            inside = inside.connectivity('all')
            region = np.asarray(inside.cell_data['RegionId'])
            take = int(region[int(inside.find_closest_cell(o + 0.25 * r * direction))])
            gone = inside.extract_cells(np.where(region == take)[0]).extract_surface(
                algorithm='dataset_surface')
            keep_inside = inside.extract_cells(np.where(region != take)[0]).extract_surface(
                algorithm='dataset_surface')
            fits = bool(((gone.points - o) @ direction).max() <= 0.98 * grown) if gone.n_points else False
            merged = rest.merge([outside, keep_inside]).clean() if gone.n_cells else None
            return merged, gone.n_cells, fits

        # the nearest vessel end wins: try both ways at the given length before
        # growing the box, so a cut does not run off to the far end of a vessel
        best, removed, why, grown, used = None, 0, '', length, n
        length_try = length
        for _ in range(3):
            for direction in (np.array(n), -np.array(n)):
                merged, n_gone, fits = cut(direction, length_try)
                if merged is None:
                    why = why or 'nothing inside the box'
                    continue
                if not fits:
                    why = 'the vessel never ends inside the box'
                    continue
                if n_gone > max_share * out.n_cells:
                    why = 'it would take %.0f%% of the model' % (100.0 * n_gone / out.n_cells)
                    continue
                best, removed, grown, used = merged, n_gone, length_try, direction
                break
            if best is not None:
                break
            length_try *= 2.0
        if best is None:
            (refused if why.startswith('it would') else skipped).append('%s: %s' % (name, why))
            continue
        n = used
        p['normal'] = [float(v) for v in n]                    # the way it actually cut
        p['box_length'] = float(grown)                         # what it actually took to reach the end
        out = best
        flatten_rim(out, o, n, 3.0 * max(half_width, r))
    if skipped or refused:
        from ..ui import console
        if skipped:
            console.warn('not cut: %s. On the Outlets step, move the cut toward the vessel end, or widen '
                         'its box so the vessel is inside it.' % '; '.join(skipped))
        if refused:
            console.warn('not cut: %s. On the Outlets step, move it toward the vessel end, narrow its box, '
                         'or turn the cut around.' % '; '.join(refused))
    conn = vtk.vtkPolyDataConnectivityFilter()
    conn.SetInputData(out)
    conn.SetExtractionModeToLargestRegion()
    conn.Update()
    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(conn.GetOutputPort())
    clean.Update()
    return clean.GetOutput()


def flatten_rim(surf, origin, normal, reach: float) -> None:
    """
    Put the rim of a fresh cut exactly on its plane.

    A box is not a linear function along a triangle edge, so the clip lands
    within a triangle of the plane; SimVascular projects the opening onto a
    fitted plane for the same reason. No point moves further than the mesh
    is coarse.
    """
    import pyvista as pv
    surf.point_data['_miros_point'] = np.arange(surf.n_points, dtype=np.int64)
    edges = surf.extract_feature_edges(boundary_edges=True, feature_edges=False,
                                       manifold_edges=False, non_manifold_edges=False)
    if edges.n_points == 0:
        surf.point_data.pop('_miros_point', None)
        return
    ids = np.asarray(edges.point_data['_miros_point'], dtype=np.int64)
    pts = surf.points
    near = ids[np.linalg.norm(pts[ids] - origin, axis=1) < reach]
    if len(near):
        d = (pts[near] - origin) @ normal
        pts[near] = pts[near] - np.outer(d, normal)
        surf.points = pts
    surf.point_data.pop('_miros_point', None)


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
