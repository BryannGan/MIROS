"""`miros setup DIR` opens the MIROS window on the Targets tab (see miros.ui.app)."""
from .app import run_app


def run_setup(case_dir) -> int:
    return run_app(case_dir, start_tab=2)
