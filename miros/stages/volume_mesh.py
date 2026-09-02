"""volume_mesh: optional tetrahedral lumen mesh for 3D projection of 1D results."""
from ..geometry.caps import read_polydata
from ..geometry.volume import volume_mesh, write_mesh_complete
from ..manifest import file_hash, value_hash
from ..ui import console


def enabled(case):
    return bool(case.config.outputs.volume_projection)


def disabled_reason(case):
    return 'outputs.volume_projection is false'


def inputs(case):
    return {'surface': file_hash(case.surface_work), 'outputs': value_hash(case.config.section('outputs'))}


def outputs(case):
    return [case.mesh_complete_dir / 'mesh-complete.mesh.vtu', case.mesh_complete_dir / 'mesh-complete.exterior.vtp']


def run(case):
    grid, ext = volume_mesh(read_polydata(case.surface_work))
    write_mesh_complete(grid, ext, case.mesh_complete_dir)
    console.info("%d points, %d tetrahedra" % (grid.n_points, grid.n_cells))
    return outputs(case)
