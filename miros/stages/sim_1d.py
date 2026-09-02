"""sim_1d: 1D solver input from the centerlines + tuned RCRs, then OneDSolver (with a bounded retry)."""
import shutil

from ..geometry.caps import read_polydata
from ..io.oned import OneDSolverError, result_files, run_onedsolver
from ..manifest import dir_hash, file_hash, value_hash
from ..rom.centerlines import Centerlines
from ..rom.mesh import Mesh
from ..rom_model import rom_parameters
from ..solvers import find_onedsolver
from ..ui import console
from .rom_model import settings


def enabled(case):
    return bool(case.config.simulation.run_1d)


def disabled_reason(case):
    return 'simulation.run_1d is false'


def inputs(case):
    return {'centerlines': file_hash(case.centerlines), 'caps': dir_hash(case.boundary_dir),
            'inflow': file_hash(case.inflow_work), 'rcrt': file_hash(case.rcrt),
            'simulation': value_hash(case.config.section('simulation'))}


def outputs(case):
    return [case.oned_input, case.oned_model, case.results_1d / 'onedsolver.log']


def _generate(case, seg_min_num):
    s = settings(case)
    s.seg_min_num = seg_min_num
    P = rom_parameters(case.work, case.boundary_dir, case.outlets_file, case.rcrt, case.inflow_work, s, 1)
    cl = Centerlines.from_polydata(read_polydata(case.centerlines), case.outlet_names())
    if not Mesh().generate(P, cl):
        raise RuntimeError("1D model generation failed")


def run(case):
    exe = find_onedsolver(case.config.solvers.onedsolver)
    if exe is None:
        raise RuntimeError("OneDSolver executable not found. Set solvers.onedsolver in case.yaml, "
                           "the MIROS_ONEDSOLVER environment variable, or put it on PATH "
                           "(or set simulation.run_1d: false).")
    s = case.config.simulation
    seg = s.seg_min_num
    for attempt in range(s.max_1d_retries + 1):
        _generate(case, seg)
        if case.results_1d.exists():
            shutil.rmtree(case.results_1d)
        console.info("OneDSolver: %s (seg_min_num %d, %d cycles)" % (exe, seg, s.cycles))
        try:
            run_onedsolver(exe, case.oned_input, case.results_1d)
            console.info("%d result files" % len(result_files(case.results_1d)))
            return outputs(case)
        except OneDSolverError as e:
            if attempt >= s.max_1d_retries:
                raise
            seg += 1
            console.warn("1D solve failed; retrying with seg_min_num %d (%d of %d)\n%s" % (
                seg, attempt + 1, s.max_1d_retries, str(e).splitlines()[-1]))
    return outputs(case)
