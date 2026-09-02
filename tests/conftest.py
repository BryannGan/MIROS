import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXAMPLE = ROOT / 'examples' / 'aorta'
SURFACE = EXAMPLE / 'clipped_seqseg_results.vtp'
INFLOW = EXAMPLE / 'inflow.flow'
REFERENCE = EXAMPLE / 'reference'
ONEDSOLVER = os.environ.get('MIROS_ONEDSOLVER', '/usr/local/sv/oneDSolver/2025-07-02/bin/OneDSolver')


@pytest.fixture(scope='session')
def surface_path():
    if not SURFACE.exists():
        pytest.skip("example surface not present: %s" % SURFACE)
    return SURFACE


@pytest.fixture(scope='session')
def inflow_path():
    if not INFLOW.exists():
        pytest.skip("example inflow not present: %s" % INFLOW)
    return INFLOW


@pytest.fixture(scope='session')
def sv_reference():
    """SimVascular-generated reference files for the validation gate, or skip."""
    files = dict(centerlines=REFERENCE / 'extracted_centerlines.vtp', zerod=REFERENCE / '0D_solver_input.json',
                 rcrt=REFERENCE / 'rcrt.dat', caps=REFERENCE / 'caps.json', inflow=INFLOW)
    for p in files.values():
        if not p.exists():
            pytest.skip("SimVascular reference file missing: %s" % p)
    return files


@pytest.fixture(scope='session')
def onedsolver():
    from miros.solvers import find_onedsolver
    exe = find_onedsolver(ONEDSOLVER if Path(ONEDSOLVER).exists() else None)
    if exe is None:
        pytest.skip("OneDSolver not found (set MIROS_ONEDSOLVER)")
    return exe


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: takes more than a few seconds")
