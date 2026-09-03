"""`miros setup DIR` opens the MIROS window on the Targets tab (see miros.ui.app)."""
from .app import run_app


def run_setup(case_dir) -> int:
    from .app import MainWindow
    return run_app(case_dir, start_tab=MainWindow.TAB_TARGETS)
