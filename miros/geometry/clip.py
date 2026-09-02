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


def clip_with_planes(surface: vtk.vtkPolyData, planes: Sequence[Dict], extent: float = 2.0) -> vtk.vtkPolyData:
    out = surface
    for k, p in enumerate(planes):
        o = np.asarray(p['origin'], dtype=float)
        n = np.asarray(p['normal'], dtype=float)
        n = n / np.linalg.norm(n)
        r = float(p['radius'])
        plane = vtk.vtkPlane()
        plane.SetOrigin(*o)
        plane.SetNormal(*(-n))            # negative (= "inside") on the distal side
        sphere = vtk.vtkSphere()
        sphere.SetCenter(*o)
        sphere.SetRadius(extent * r)
        region = vtk.vtkImplicitBoolean()
        region.SetOperationTypeToIntersection()
        region.AddFunction(plane)
        region.AddFunction(sphere)
        clipper = vtk.vtkClipPolyData()
        clipper.SetInputData(out)
        clipper.SetClipFunction(region)
        clipper.InsideOutOff()             # keep function > 0: everything but the distal half-ball
        clipper.Update()
        out = clipper.GetOutput()
        if out.GetNumberOfCells() == 0:
            raise ValueError("outlet plane %d (%s) removed the whole surface" % (k, p.get('name', '')))
    conn = vtk.vtkPolyDataConnectivityFilter()
    conn.SetInputData(out)
    conn.SetExtractionModeToLargestRegion()
    conn.Update()
    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(conn.GetOutputPort())
    clean.Update()
    return clean.GetOutput()


def plane_names_for_caps(caps, planes: Sequence[Dict]) -> List[str]:
    """Name each cap (in the given order) after the nearest plane's `name`."""
    names = []
    for c in caps:
        j = int(np.argmin([np.linalg.norm(np.asarray(p['origin'], float) - c.centroid) for p in planes]))
        names.append(planes[j].get('name') or ('cap_%d' % (j + 1)))
    if len(set(names)) != len(names):
        raise ValueError("outlet planes could not be matched one-to-one to caps: %s" % names)
    return names
