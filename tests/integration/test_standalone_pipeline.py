"""Surface -> ROM -> 0D -> 1D -> extraction with nothing from SimVascular installed."""
import shutil
import sys

import numpy as np
import pytest

from miros.io.oned import result_files, run_onedsolver
from miros.rom_model import RomSettings, build_rom_model

pytestmark = pytest.mark.slow


def test_no_simvascular_module_is_imported():
    import miros.rom_model  # noqa: F401  (imports everything the pipeline needs)
    assert not any(m == 'sv' or m.startswith('sv.') for m in sys.modules)


def test_build_and_solve(surface_path, inflow_path, tmp_path):
    r = build_rom_model(surface_path, tmp_path, inflow_path, settings=RomSettings(cycles=2), verbose=False)
    assert r.zerod_json.exists() and r.oned_input.exists() and r.centerlines.exists()
    assert len(r.outlet_names) == 5 and r.inlet_name not in r.outlet_names
    assert (r.boundary_dir / 'inlet.vtp').exists() and (r.boundary_dir / 'wall.vtp').exists()

    pysvzerod = pytest.importorskip('pysvzerod')
    s = pysvzerod.Solver(str(r.zerod_json)); s.run()
    res = s.get_full_result()
    assert len(res['name']) > 0 and np.isfinite(np.asarray(res['pressure_in'])).all()


def test_onedsolver_runs_on_builtin_model(surface_path, inflow_path, onedsolver, tmp_path):
    r = build_rom_model(surface_path, tmp_path, inflow_path, settings=RomSettings(cycles=1), write_0d=False, verbose=False)
    run_onedsolver(onedsolver, r.oned_input, tmp_path / '1D_results')
    assert len(result_files(tmp_path / '1D_results')) >= 5
