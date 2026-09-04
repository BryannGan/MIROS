"""preprocess: surface -> (unit-converted, optionally clipped and remeshed) surface + caps."""
import json
from pathlib import Path

import numpy as np
import vtk

from ..geometry import caps as C
from ..geometry.clip import clip_with_planes, plane_names_for_caps
from ..manifest import file_hash, value_hash
from ..ui import console


def source_surface(case):
    """The surface this stage starts from: model.surface, or SeqSeg's output when segmenting."""
    if case.config.segmentation.image:
        return case.work / 'seqseg_surface.vtp'
    return case.resolve(case.config.model.surface)


def outlet_planes(case):
    """model.outlets if given, else the planes the segment stage proposed (if any)."""
    m = case.config.model
    if m.outlets:
        return [dict(p) for p in m.outlets if p.get('use', True)]
    proposed = case.work / 'outlets_proposed.json'
    if case.config.segmentation.image and proposed.exists():
        return [p for p in json.loads(proposed.read_text()) if p.get('use', True)]
    return []


def inputs(case):   # noqa: D401 - the model section covers the smoothing settings too
    d = {'surface': file_hash(source_surface(case)), 'model': value_hash(case.config.section('model'))}
    proposed = case.work / 'outlets_proposed.json'
    if case.config.segmentation.image and proposed.exists():
        d['proposed_outlets'] = file_hash(proposed)
    return d


def outputs(case):
    return [case.surface_work, case.caps_json, case.boundary_dir / 'inlet.vtp', case.boundary_dir / 'wall.vtp']


def _scale(surface, factor):
    tf = vtk.vtkTransform()
    tf.Scale(factor, factor, factor)
    flt = vtk.vtkTransformPolyDataFilter()
    flt.SetInputData(surface)
    flt.SetTransform(tf)
    flt.Update()
    return flt.GetOutput()


def run(case):
    m = case.config.model
    src = source_surface(case)
    surf = C.read_polydata(src)
    console.info("surface: %s (%d points)" % (src.name, surf.GetNumberOfPoints()))
    names = m.cap_names
    planes = outlet_planes(case)
    units = case.config.segmentation.units if case.config.segmentation.image else m.units
    if m.smooth_iterations > 0:
        from ..geometry.smooth import smooth_surface, wall_movement
        smoothed = smooth_surface(surf, iterations=m.smooth_iterations, pass_band=m.smooth_pass_band)
        moved = wall_movement(surf, smoothed)
        surf = smoothed
        console.info("smoothed the wall: %d passes at pass band %g%s" % (
            m.smooth_iterations, m.smooth_pass_band,
            '' if moved is None else ', the wall moved %.3f mm on average' % (10.0 * moved)))
    if planes:
        surf = clip_with_planes(surf, planes)
        console.info("clipped %d outlet planes%s" % (len(planes), '' if m.outlets else ' (proposed by the segment stage)'))
    if units == 'mm':
        surf = _scale(surf, 0.1)
        console.info("converted mm -> cm")
    if m.remesh:
        from ..geometry.remesh import remesh
        surf = remesh(surf, edge_size=m.remesh_edge_size)
        console.info("remeshed to %d points" % surf.GetNumberOfPoints())
    surf = C.triangulate_and_clean(surf)

    if planes and names is None:
        tmp = C.make_caps(surf)
        pl = planes
        if units == 'mm':
            pl = [dict(p, origin=[0.1 * v for v in p['origin']], radius=0.1 * p['radius']) for p in pl]
        names = plane_names_for_caps(tmp, pl)
        inlet = m.inlet or next((p['name'] for p in pl if p.get('inlet')), None)
        if inlet not in names:                 # the inlet plane cut no cap of its own
            inlet = None                       # fall back to the largest cap
    else:
        inlet = m.inlet
    caps = C.make_caps(surf, inlet=inlet, names=names)
    ordered = [C.inlet_cap(caps)] + C.outlet_caps(caps)

    case.work.mkdir(parents=True, exist_ok=True)
    C.write_polydata(case.surface_work, surf)
    outlet_names = C.write_boundary_dir(surf, ordered, case.boundary_dir)
    info = {
        'inlet': C.inlet_cap(caps).name,
        'outlets': outlet_names,
        'names_by_area': [c.name for c in caps],
        'caps': {c.name: {'area': c.area, 'radius': c.radius, 'centroid': c.centroid.tolist(),
                          'normal': c.normal.tolist(), 'inlet': c.is_inlet} for c in caps},
    }
    case.caps_json.write_text(json.dumps(info, indent=2))
    console.table(['cap', 'area [cm²]', 'radius [cm]', 'role'],
                  [(c.name, '%.4f' % c.area, '%.3f' % c.radius, 'inlet' if c.is_inlet else 'outlet') for c in ordered])
    return outputs(case)
