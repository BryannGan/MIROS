
# from sv_rom_extract_results.extract_results import run as extract_run  # programmatic entry
# from sv_rom_extract_results.manage import init_logging

from pathlib import Path
import numpy as np
import pdb
import vtk
from vtk.util import numpy_support
from vtk.util.numpy_support import vtk_to_numpy as v2n
from vtk.util.numpy_support import numpy_to_vtk as n2v
import os 
import shutil
import time
import sys
import csv
import warnings
import subprocess
# ========================================================================
# ============================ intialize  ================================

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
from package import *

from pathlib import Path
import os, sys

# If sv_rom_extract_results is installed in a known SimVascular site-packages:
# sv_py_bin should already be defined by your 'from package import *'
SV_EXTRACT_PKG_DIR = Path(os.path.dirname(sv_py_bin)) / "Python3.11" / "site-packages" / "sv_rom_extract_results"
SV_SITE_PACKAGES   = SV_EXTRACT_PKG_DIR.parent  # <- parent of the package

# 1) Ensure parent-of-package is on sys.path (NOT the package dir itself)
if str(SV_SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(SV_SITE_PACKAGES))

# 2) Import using the package-qualified names (avoid name collisions)
from sv_rom_extract_results.extract_results import run as extract_run
from sv_rom_extract_results.manage import init_logging, get_logger_name, get_log_file_name

# parameter/parameters naming differs across copies; handle both.
try:
    from sv_rom_extract_results import parameters as sv_params
except ImportError:
    from sv_rom_extract_results import parameter as sv_params

from sv_rom_extract_results import solver as sv_solver
# ========================================================================




def _canon_cfg(cfg: dict) -> dict:
    """Normalize config to what extract_run(**kwargs) expects."""
    cfg = dict(cfg)

    # Strings for comma-separated args the script expects.
    for key in ("data_names", "segments", "time_range"):
        v = cfg.get(key)
        if isinstance(v, (list, tuple)):
            cfg[key] = ",".join(map(str, v))

    # Flags must be strings like "on"/"off" or booleans; both are accepted.
    # We'll convert booleans to the expected string-y forms for consistency.
    def _bool_to_onoff(b): return "on" if b else "off"
    def _bool_to_truefalse(b): return "true" if b else "false"

    if "display_geometry" in cfg and isinstance(cfg["display_geometry"], bool):
        cfg["display_geometry"] = _bool_to_onoff(cfg["display_geometry"])
    if "plot" in cfg and isinstance(cfg["plot"], bool):
        cfg["plot"] = _bool_to_onoff(cfg["plot"])

    for key in ("all_segments", "outlet_segments", "select_segments"):
        if key in cfg and isinstance(cfg[key], bool):
            cfg[key] = _bool_to_truefalse(cfg[key])

    return cfg

def extract_once(config: dict):
    cfg = _canon_cfg(config)
    outdir = Path(cfg["output_directory"])
    outdir.mkdir(parents=True, exist_ok=True)

    # initialize logging where outputs go
    init_logging(str(outdir))

    # run the convert/extract pipeline
    msg = extract_run(**cfg)
    print(msg)

if __name__ == "__main__":
    # --- Example: 0D ---
    # config_0d = {
    #     "model_order": 0,
    #     "results_directory": res_folder_0D,
    #     "solver_file_name": os.path.join(master_folder, '0D_solver_input.json'),        # base name is used to find *_branch_results.npy
    #     "output_directory": res_folder_0D, # save t0?
    #     "output_file_name": "surf_name",
    #     "time_range": "11,12",               # REQUIRED for 0D
    #     # Optional projection to centerline/3D:
    #     "centerlines_file": os.path.join(master_folder, 'extracted_centerlines.vtp'),
    #     "walls_mesh_file": os.path.join(caps_folder, 'wall.vtp'),
    #     # "volume_mesh_file": "mesh-complete.mesh.vtu",
    # }

    # --- Example: 1D ---
    print('Extracting 1D results...')
    config_1d = {
        "model_order": 1,
        "results_directory": master_folder,
        "solver_file_name": '1D_solver_input.in',        # base name is used to find *_branch_results.npy
        "output_directory": res_folder_1D,
        "output_file_name": "surf_name",
        "output_format": "csv",
        "data_names": "flow,pressure,area",    # must match *.dat suffixes present
        # Pick one of the selection methods:
        # "segments": "Group0_Seg0,Group0_Seg1",
        "outlet_segments": True,               # or all_segments=True
        # Optional projections:
        "centerlines_file": os.path.join(master_folder, 'extracted_centerlines.vtp'),
        "walls_mesh_file": os.path.join(caps_folder, 'wall.vtp'),
        #"volume_mesh_file": os.path.join(caps_folder, 'mesh-complete.mesh.vtu'),
        # Optional visuals/plots if you later use the CLI path:
        "plot": "On",
        "display_geometry": "On",
        
    }

    extract_once(config_1d)


