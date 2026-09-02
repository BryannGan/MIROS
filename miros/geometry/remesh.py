"""
Isotropic surface remeshing with pyacvd (ACVD clustering), replacing
SimVascular's MMG remesh. Works on open surfaces; boundary loops are
preserved approximately, so caps should be recomputed afterwards.
"""
from typing import Optional

import numpy as np
import pyvista as pv
import vtk

from .caps import fill_small_loops


def estimate_edge_size(surface: vtk.vtkPolyData) -> float:
    """
    Edge size for a uniform remesh, from the model's own scale: the median
    existing edge length, clamped to [0.5%, 3%] of the largest bounding-box
    dimension.
    """
    mesh = pv.wrap(surface).triangulate().clean()
    edges = mesh.extract_all_edges()
    lines = edges.lines.reshape(-1, 3)[:, 1:]
    lengths = np.linalg.norm(edges.points[lines[:, 0]] - edges.points[lines[:, 1]], axis=1)
    lengths = lengths[lengths > 0]
    med = float(np.median(lengths)) if len(lengths) else 0.0
    b = mesh.bounds
    max_dim = max(b[1] - b[0], b[3] - b[2], b[5] - b[4])
    return float(np.clip(med if med > 0 else 0.015 * max_dim, 0.005 * max_dim, 0.03 * max_dim))


def remesh(surface: vtk.vtkPolyData, edge_size: Optional[float] = None,
           smooth_iterations: int = 0) -> pv.PolyData:
    """
    Remesh to roughly uniform triangles of the given edge size (default:
    estimate_edge_size). Optional Taubin smoothing first.
    """
    import pyacvd

    mesh = pv.wrap(surface).triangulate().clean()
    if smooth_iterations > 0:
        mesh = mesh.smooth_taubin(n_iter=smooth_iterations, pass_band=0.1)
    if edge_size is None:
        edge_size = estimate_edge_size(mesh)
    # vertices of an equilateral triangulation with edge h over area A: ~ 2A / (sqrt(3) h^2)
    n_points = int(max(2 * mesh.area / (np.sqrt(3.0) * edge_size ** 2), 100))
    clus = pyacvd.Clustering(mesh)
    if mesh.n_points < 3 * n_points:
        clus.subdivide(2)
    clus.cluster(n_points)
    out = clus.create_mesh().clean()
    # ACVD can drop an isolated triangle, leaving a 3-point boundary loop
    return pv.wrap(fill_small_loops(out)).clean()
