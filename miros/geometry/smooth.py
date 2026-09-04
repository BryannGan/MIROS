"""
Smoothing for a segmented vessel surface.

A surface straight out of marching cubes carries the voxel grid with it:
terraced walls, a rim of stair steps at every cut. SimVascular smooths such
a surface with a windowed sinc filter, which moves points along the surface
without shrinking the vessel the way plain Laplacian smoothing does, and
this follows their recipe (`sv_auto_lv_modeling`: 20 iterations at pass band
0.02 straight off marching cubes, then 50 iterations after clipping, with
boundary smoothing off both times so a fresh cut rim is left where it is).
"""
from typing import Optional

import vtk


def smooth_surface(surface: vtk.vtkPolyData, iterations: int = 20, pass_band: float = 0.02,
                   boundary: bool = False, feature_edges: bool = False) -> vtk.vtkPolyData:
    """
    Windowed sinc smoothing.

    `pass_band` is what to keep: smaller smooths harder (0.001 is very
    smooth, 0.1 barely touches the surface). `boundary` False leaves the
    points on an open rim where they are, which is what you want after
    cutting the vessel ends open.
    """
    if iterations <= 0:
        return surface
    f = vtk.vtkWindowedSincPolyDataFilter()
    f.SetInputData(surface)
    f.SetNumberOfIterations(int(iterations))
    f.SetPassBand(float(pass_band))
    f.SetBoundarySmoothing(bool(boundary))
    f.SetFeatureEdgeSmoothing(bool(feature_edges))
    f.NonManifoldSmoothingOn()
    f.NormalizeCoordinatesOn()          # without this the pass band means different things per model
    f.Update()
    out = f.GetOutput()
    clean = vtk.vtkCleanPolyData()
    clean.SetInputData(out)
    clean.Update()
    return clean.GetOutput()


def wall_movement(before: vtk.vtkPolyData, after: vtk.vtkPolyData) -> Optional[float]:
    """How far the smoothing moved the wall, in cm: the mean over the points it kept."""
    import numpy as np
    from vtk.util.numpy_support import vtk_to_numpy as v2n
    if before.GetNumberOfPoints() != after.GetNumberOfPoints():
        return None
    a = v2n(before.GetPoints().GetData())
    b = v2n(after.GetPoints().GetData())
    return float(np.linalg.norm(b - a, axis=1).mean())
