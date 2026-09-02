"""
Caps of an open vessel surface.

An "open" surface is one whose inlet and outlets have been clipped away, so
every boundary loop of the mesh is a vessel cross-section. This module finds
those loops, triangulates each into a cap, measures it, and can write the
boundary-surfaces directory (inlet.vtp, cap_*.vtp, wall.vtp) that the
reduced-order model builder reads.

No SimVascular dependency: everything is VTK.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk as n2v
from vtk.util.numpy_support import vtk_to_numpy as v2n


@dataclass
class Cap:
    """One boundary loop of the surface, triangulated."""
    name: str
    centroid: np.ndarray          # (3,) area centroid of the cap
    normal: np.ndarray            # (3,) unit normal pointing OUT of the vessel
    area: float
    loop: np.ndarray              # (n, 3) ordered loop points
    polydata: vtk.vtkPolyData     # triangulated cap surface
    is_inlet: bool = False

    @property
    def radius(self) -> float:
        """Equivalent circular radius."""
        return float(np.sqrt(self.area / np.pi))


# ----------------------------------------------------------------------------
# reading / basic filters

def read_polydata(path) -> vtk.vtkPolyData:
    path = str(path)
    if path.lower().endswith('.vtp'):
        reader = vtk.vtkXMLPolyDataReader()
    elif path.lower().endswith('.stl'):
        reader = vtk.vtkSTLReader()
    elif path.lower().endswith('.ply'):
        reader = vtk.vtkPLYReader()
    else:
        raise ValueError("Unsupported surface format: " + path)
    reader.SetFileName(path)
    reader.Update()
    return reader.GetOutput()


def write_polydata(path, polydata: vtk.vtkPolyData) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(str(path))
    writer.SetInputData(polydata)
    writer.Write()


def triangulate_and_clean(surface: vtk.vtkPolyData) -> vtk.vtkPolyData:
    """Triangles only, duplicate points merged, unused points dropped."""
    tri = vtk.vtkTriangleFilter()
    tri.SetInputData(surface)
    tri.PassLinesOff()
    tri.PassVertsOff()
    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(tri.GetOutputPort())
    clean.PointMergingOn()
    clean.Update()
    return clean.GetOutput()


# ----------------------------------------------------------------------------
# boundary loops

def boundary_loops(surface: vtk.vtkPolyData) -> List[np.ndarray]:
    """
    Ordered point loops of every boundary of the surface.

    Returns a list of (n, 3) arrays, each an ordered closed loop (last point
    connects back to the first).
    """
    edges = vtk.vtkFeatureEdges()
    edges.SetInputData(surface)
    edges.BoundaryEdgesOn()
    edges.FeatureEdgesOff()
    edges.NonManifoldEdgesOff()
    edges.ManifoldEdgesOff()
    edges.ColoringOff()

    strip = vtk.vtkStripper()
    strip.SetInputConnection(edges.GetOutputPort())
    strip.JoinContiguousSegmentsOn()
    strip.Update()
    stripped = strip.GetOutput()

    points = v2n(stripped.GetPoints().GetData())
    loops = []
    lines = stripped.GetLines()
    ids = vtk.vtkIdList()
    lines.InitTraversal()
    while lines.GetNextCell(ids):
        idx = [ids.GetId(i) for i in range(ids.GetNumberOfIds())]
        if len(idx) > 1 and idx[0] == idx[-1]:
            idx = idx[:-1]
        if len(idx) >= 3:
            loops.append(points[idx])
    return loops


def _loop_polydata(loop: np.ndarray) -> vtk.vtkPolyData:
    pd = vtk.vtkPolyData()
    pts = vtk.vtkPoints()
    pts.SetData(n2v(np.ascontiguousarray(loop, dtype=np.float64), deep=True))
    pd.SetPoints(pts)
    n = len(loop)
    line = vtk.vtkPolyLine()
    line.GetPointIds().SetNumberOfIds(n + 1)
    for i in range(n):
        line.GetPointIds().SetId(i, i)
    line.GetPointIds().SetId(n, 0)
    cells = vtk.vtkCellArray()
    cells.InsertNextCell(line)
    pd.SetLines(cells)
    return pd


def triangulate_loop(loop: np.ndarray) -> vtk.vtkPolyData:
    """Planar-ish triangulation of a closed loop (handles concave loops)."""
    tri = vtk.vtkContourTriangulator()
    tri.SetInputData(_loop_polydata(loop))
    tri.Update()
    out = vtk.vtkPolyData()
    out.DeepCopy(tri.GetOutput())
    return out


def _polygon_area_centroid_normal(loop: np.ndarray):
    """Area, area-centroid and unit normal of a (nearly) planar loop."""
    c0 = loop.mean(axis=0)
    q = loop - c0
    nxt = np.roll(q, -1, axis=0)
    cross = np.cross(q, nxt)                      # 2 * signed triangle areas
    n = cross.sum(axis=0)
    area = 0.5 * np.linalg.norm(n)
    if area <= 0:
        return 0.0, c0, np.array([0.0, 0.0, 1.0])
    n = n / (2.0 * area)
    # area-weighted centroid of the fan triangles about c0
    w = 0.5 * (cross @ n)                         # signed triangle areas
    tri_c = (q + nxt) / 3.0                       # triangle centroids relative to c0
    centroid = c0 + (w[:, None] * tri_c).sum(axis=0) / w.sum()
    return float(area), centroid, n


# ----------------------------------------------------------------------------
# caps

def make_caps(surface: vtk.vtkPolyData, inlet: Optional[str] = None,
              names: Optional[Sequence[str]] = None) -> List[Cap]:
    """
    Find every boundary loop of an open surface and turn it into a Cap.

    Caps are named cap_1, cap_2, ... in order of decreasing area unless
    `names` is given (same order as the sorted loops). `inlet` selects the
    inlet by name; if None, the largest cap is the inlet.
    Normals are oriented to point out of the vessel.
    """
    surface = triangulate_and_clean(surface)
    loops = boundary_loops(surface)
    if not loops:
        raise ValueError("Surface has no boundary loops: is it already closed? "
                         "Clip the inlet and outlets open first.")

    surf_points = v2n(surface.GetPoints().GetData())
    caps = []
    for loop in loops:
        area, centroid, normal = _polygon_area_centroid_normal(loop)
        radius = np.sqrt(area / np.pi)
        # orient outward: away from the wall points near the loop
        d = np.linalg.norm(surf_points - centroid, axis=1)
        near = surf_points[(d > 0.5 * radius) & (d < 3.0 * radius)]
        if len(near) > 0 and np.dot(normal, centroid - near.mean(axis=0)) < 0:
            normal = -normal
        caps.append(Cap(name='', centroid=centroid, normal=normal, area=area,
                        loop=loop, polydata=triangulate_loop(loop)))

    caps.sort(key=lambda c: -c.area)
    if names is not None:
        if len(names) != len(caps):
            raise ValueError("%d names given for %d caps" % (len(names), len(caps)))
        for cap, name in zip(caps, names):
            cap.name = name
    else:
        for i, cap in enumerate(caps):
            cap.name = 'cap_%d' % (i + 1)

    if inlet is None:
        caps[0].is_inlet = True
    else:
        matches = [c for c in caps if c.name == inlet]
        if not matches:
            raise ValueError("Inlet '%s' is not one of the caps: %s" % (inlet, [c.name for c in caps]))
        matches[0].is_inlet = True
    return caps


def outlet_caps(caps: Sequence[Cap]) -> List[Cap]:
    return [c for c in caps if not c.is_inlet]


def inlet_cap(caps: Sequence[Cap]) -> Cap:
    return [c for c in caps if c.is_inlet][0]


def close_surface(surface: vtk.vtkPolyData, caps: Sequence[Cap]) -> vtk.vtkPolyData:
    """
    Closed surface = wall + all caps, points merged. A cell array 'CapId'
    is 0 on the wall and k+1 on cap k (in the order of `caps`).
    """
    surface = triangulate_and_clean(surface)
    append = vtk.vtkAppendPolyData()

    wall = vtk.vtkPolyData()
    wall.DeepCopy(surface)
    ids = np.zeros(wall.GetNumberOfCells(), dtype=np.int32)
    arr = n2v(ids, deep=True)
    arr.SetName('CapId')
    wall.GetCellData().AddArray(arr)
    append.AddInputData(wall)

    for k, cap in enumerate(caps):
        pd = vtk.vtkPolyData()
        pd.DeepCopy(cap.polydata)
        ids = np.full(pd.GetNumberOfCells(), k + 1, dtype=np.int32)
        arr = n2v(ids, deep=True)
        arr.SetName('CapId')
        pd.GetCellData().AddArray(arr)
        append.AddInputData(pd)

    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(append.GetOutputPort())
    clean.PointMergingOn()
    clean.Update()

    normals = vtk.vtkPolyDataNormals()
    normals.SetInputConnection(clean.GetOutputPort())
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.SplittingOff()
    normals.Update()
    return normals.GetOutput()


def write_boundary_dir(surface: vtk.vtkPolyData, caps: Sequence[Cap], out_dir) -> List[str]:
    """
    Write inlet.vtp, cap_<name>.vtp for each outlet, and wall.vtp into
    out_dir, and return the outlet names in the order written. This is the
    layout the ROM builder's boundary_surfaces_dir expects.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob('*.vtp'):
        old.unlink()
    write_polydata(out_dir / 'wall.vtp', triangulate_and_clean(surface))
    write_polydata(out_dir / 'inlet.vtp', inlet_cap(caps).polydata)
    names = []
    for cap in outlet_caps(caps):
        write_polydata(out_dir / (cap.name + '.vtp'), cap.polydata)
        names.append(cap.name)
    return names


def fill_small_loops(surface: vtk.vtkPolyData, max_points: int = 5) -> vtk.vtkPolyData:
    """
    Close boundary loops with at most `max_points` points (single missing
    triangles left by remeshing). A real vessel cross-section always has
    many more boundary points than that at any usable edge size.
    """
    surface = triangulate_and_clean(surface)
    small = [loop for loop in boundary_loops(surface) if len(loop) <= max_points]
    if not small:
        return surface
    append = vtk.vtkAppendPolyData()
    append.AddInputData(surface)
    for loop in small:
        append.AddInputData(triangulate_loop(loop))
    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(append.GetOutputPort())
    clean.PointMergingOn()
    clean.Update()
    return clean.GetOutput()


def cap_summary(caps: Sequence[Cap]) -> str:
    rows = ["%-10s %10s %9s %9s  %s" % ('cap', 'area', 'radius', 'inlet', 'centroid')]
    for c in caps:
        rows.append("%-10s %10.4f %9.4f %9s  (%.2f, %.2f, %.2f)" % (
            c.name, c.area, c.radius, 'yes' if c.is_inlet else '', *c.centroid))
    return "\n".join(rows)
