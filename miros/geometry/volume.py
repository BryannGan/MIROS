"""
Tetrahedral volume mesh of the vessel lumen with tetgen, replacing
SimVascular's TetGen wrapper. Only needed to paint 1D results onto a 3D
lumen for ParaView, so it is an optional stage.

The open surface is remeshed coarsely first (tetgen is far more robust on
a uniform surface and the result is only for visualization), capped, and
tetrahedralized with switches p q<ratio> a<max volume> Y Q: piecewise
linear complex, quality bound, volume bound, no Steiner points on the
boundary (which is what makes tetgen fail on raw segmentation surfaces),
quiet.
"""
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np
import pyvista as pv
import vtk

from . import caps as C
from .remesh import remesh


def volume_mesh(surface: vtk.vtkPolyData, edge_size: Optional[float] = None,
                quality_ratio: float = 1.5) -> Tuple[pv.UnstructuredGrid, pv.PolyData]:
    """
    surface: the OPEN clipped surface.
    edge_size: target element size (default 3% of the largest bounding-box
    dimension, the value the old pipeline used).

    Returns (volume grid, exterior surface), both with a GlobalNodeID point
    array as the result projection expects.
    """
    import tetgen

    open_surf = pv.wrap(surface).triangulate().clean()
    if edge_size is None:
        b = open_surf.bounds
        edge_size = 0.03 * max(b[1] - b[0], b[3] - b[2], b[5] - b[4])
    # surface edge for the remesh: finer than the volume elements so the
    # lumen shape survives, but far coarser than a segmentation surface
    coarse = remesh(open_surf, edge_size=0.5 * edge_size)
    caps = C.make_caps(coarse)
    closed = pv.wrap(C.close_surface(coarse, caps)).triangulate().clean()
    if not closed.is_manifold or closed.n_open_edges:
        raise RuntimeError("closed surface for volume meshing is not watertight")

    max_volume = edge_size ** 3 / (6.0 * np.sqrt(2.0))   # regular tetrahedron of edge h
    tet = tetgen.TetGen(closed)
    tet.tetrahedralize(switches='pq%.2fa%.6fYQ' % (quality_ratio, max_volume))
    grid = tet.grid
    grid.point_data['GlobalNodeID'] = np.arange(grid.n_points, dtype=np.int32)
    exterior = grid.extract_surface()
    exterior.point_data['GlobalNodeID'] = np.arange(exterior.n_points, dtype=np.int32)
    return grid, exterior


def write_mesh_complete(grid: pv.UnstructuredGrid, exterior: pv.PolyData, out_dir) -> Tuple[Path, Path]:
    """Write mesh-complete.mesh.vtu and mesh-complete.exterior.vtp into out_dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    vtu = out_dir / 'mesh-complete.mesh.vtu'
    vtp = out_dir / 'mesh-complete.exterior.vtp'
    grid.save(str(vtu))
    exterior.save(str(vtp))
    return vtu, vtp
