"""preprocess: surface -> (unit-converted, optionally clipped and remeshed) surface + caps."""
import json

import numpy as np
import vtk

from ..geometry import caps as C
from ..geometry.clip import clip_with_planes, plane_names_for_caps
from ..manifest import file_hash, value_hash
from ..ui import console


def inputs(case):
    m = case.config.model
    return {'surface': file_hash(case.resolve(m.surface)), 'model': value_hash(case.config.section('model'))}


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
    surf = C.read_polydata(case.resolve(m.surface))
    console.info("surface: %s (%d points)" % (case.resolve(m.surface).name, surf.GetNumberOfPoints()))
    names = m.cap_names
    if m.outlets:
        surf = clip_with_planes(surf, m.outlets)
        console.info("clipped %d outlet planes" % len(m.outlets))
    if m.units == 'mm':
        surf = _scale(surf, 0.1)
        console.info("converted mm -> cm")
    if m.remesh:
        from ..geometry.remesh import remesh
        surf = remesh(surf, edge_size=m.remesh_edge_size)
        console.info("remeshed to %d points" % surf.GetNumberOfPoints())
    surf = C.triangulate_and_clean(surf)

    if m.outlets and names is None:
        tmp = C.make_caps(surf)
        planes = m.outlets
        if m.units == 'mm':
            planes = [dict(p, origin=[0.1 * v for v in p['origin']], radius=0.1 * p['radius']) for p in planes]
        names = plane_names_for_caps(tmp, planes)
        inlet = m.inlet or next((p['name'] for p in planes if p.get('inlet')), None)
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
