import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEST_CASE = ROOT / 'test_Linux_Mac'
SURFACE = TEST_CASE / 'clipped_seqseg_results.vtp'
INFLOW = TEST_CASE / 'inflow_1d.flow'
SV_CENTERLINES = TEST_CASE / 'extracted_centerlines.vtp'      # SimVascular reference (generated, not tracked)
SV_CAPS = TEST_CASE / 'caps_and_wall'
SV_ZEROD = TEST_CASE / '0D_solver_input.json'
ONEDSOLVER = os.environ.get('MIROS_ONEDSOLVER', '/usr/local/sv/oneDSolver/2025-07-02/bin/OneDSolver')


@pytest.fixture(scope='session')
def surface_path():
    if not SURFACE.exists():
        pytest.skip("test surface not present: %s" % SURFACE)
    return SURFACE


@pytest.fixture(scope='session')
def sv_reference():
    """Paths of the SimVascular-generated reference files, or skip."""
    for p in (SV_CENTERLINES, SV_CAPS, SV_ZEROD, INFLOW):
        if not p.exists():
            pytest.skip("SimVascular reference file missing: %s" % p)
    return dict(centerlines=SV_CENTERLINES, caps=SV_CAPS, zerod=SV_ZEROD, inflow=INFLOW)


@pytest.fixture(scope='session')
def onedsolver():
    if not Path(ONEDSOLVER).exists():
        pytest.skip("OneDSolver not found (set MIROS_ONEDSOLVER)")
    return ONEDSOLVER


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: takes more than a few seconds")
