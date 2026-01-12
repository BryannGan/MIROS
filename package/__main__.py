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
from package import *
import warnings
import subprocess
import matplotlib

# ========================================================================
# ============================ intialize  ================================

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
env = os.environ.copy()
prev = env.get('PYTHONPATH', '')
env['PYTHONPATH'] = project_root + (os.pathsep + prev if prev else '')

# ========================================================================
# ============================ run mode selection ========================
# ========================================================================

print("\n" + "=" * 70)
print("  MIROS - Medical Image to Reduced-Order Simulation")
print("=" * 70)
print("\n  Select run mode:\n")
print("    [1] Full workflow - Run entire pipeline (preprocessing, simulations, extraction)")
print("    [2] Extract 1D results only - Skip to 1D result extraction")
print("    [3] Extract 0D results only - Skip to 0D result extraction")
print("")

run_mode = None
while run_mode not in ['1', '2', '3']:
    run_mode = input("  Enter choice (1, 2, or 3): ").strip()
    if run_mode not in ['1', '2', '3']:
        print("  Invalid choice. Please enter 1, 2, or 3.")

if run_mode in ['2', '3']:
    print("\n  " + "-" * 60)
    print("  Skipping to result extraction...")
    print("  " + "-" * 60 + "\n")



pkg_dir = os.path.dirname(__file__)
post_process_seqseg  = os.path.join(pkg_dir, 'post_process_seqseg.py')
sv_preprocess = os.path.join(pkg_dir, 'sv_preprocess.py')
gen_params_cl_run_1D         = os.path.join(pkg_dir, 'gen_params_cl_run_1D.py')
gen_params0D         = os.path.join(pkg_dir, 'gen_params0D.py')
gen_inflow        = os.path.join(pkg_dir, 'gen_inflow.py')
run_0D         = os.path.join(pkg_dir, 'run_0D.py')
extract_1d_res = os.path.join(pkg_dir, 'extract_1d_res.py')
extract_0d_res = os.path.join(pkg_dir, 'extract_0d_res.py')

# # ========================================================================
# # ======================= post-process seqseg results  ===================

# '''
# This part automaticall clips and define outlet for the seqseg model.
# However, dependes on your model complexity,
# instead of using this code which replies on a non-robust extracted centerline,
# you may use SimVascular to clip the caps open tailering to your needs.
# '''
# if automatic_define_outlets:
#   if Windows:
#       # copy your current environment, but prepend project_root to PYTHONPATH

#       # run bat via shell, but with PYTHONPATH set
#       subprocess.run(
#           f'"{sv_bat}" --python -- "{post_process_seqseg}"',
#           cwd=sv_dir,
#           shell=True,
#           check=True,
#           text=True,
#           env=env,
#       )
#   else:
#       subprocess.run(
#           [local_py_bin, post_process_seqseg],
#           cwd=os.path.dirname(__file__),
#           text=True,
#           check=True,
#       )

# '''
# notes:
# This will output the clipped seqseg model to master_folder's <clipped_seqseg_results> path, along with clipping boxes
# '''
# # =======================================================================
# # ============================ pre-process ==============================

# =======================================================================
# ============================ FULL WORKFLOW (Mode 1) ===================
# =======================================================================

if run_mode == '1':
    # =======================================================================
    # ============================ pre-process ==============================
    if Windows:
        subprocess.run(
            f'"{sv_bat}" --python -- "{sv_preprocess}"',
            cwd=sv_dir,
            shell=True,
            check=True,
            text=True,
            env=env,
        )
    else:
        subprocess.run(
            [sv_py_bin, "--python", "--", sv_preprocess],
            cwd=os.path.dirname(__file__),
            text=True,
            check=True,
            env=env
        )

    # =======================================================================
    # =============================== get inflow ============================
    subprocess.run(
        [local_py_bin, gen_inflow],
        cwd=os.path.dirname(__file__),
        text=True,
        check=True
    )

    # =======================================================================
    # ============================= set up 1D and run 1D ====================
    if Windows:
        subprocess.run(
            f'"{sv_bat}" --python -- "{gen_params_cl_run_1D}"',
            cwd=sv_dir,
            shell=True,
            check=True,
            text=True,
            env=env,
        )
    else:
        subprocess.run(
            [sv_py_bin, "--python", "--", gen_params_cl_run_1D],
            cwd=os.path.dirname(__file__),
            text=True,
            check=True
        )

# =======================================================================
# ============================ extract 1D results =======================
# This runs for mode 1 (full) or mode 2 (1D extraction only)
# =======================================================================

if run_mode in ['1', '2']:
    print("\n" + "=" * 70)
    print("  [STEP] 1D Result Extraction")
    print("=" * 70)

    if Windows:
        subprocess.run(
            f'"{sv_bat}" --python -- "{extract_1d_res}"',
            cwd=sv_dir,
            shell=True,
            check=True,
            text=True,
            env=env,
        )
    else:
        subprocess.run(
            [local_py_bin, extract_1d_res],
            cwd=os.path.dirname(__file__),
            text=True,
            check=True,
            env=env
        )

# =======================================================================
# ============================ 0D WORKFLOW (Mode 1 only) ================
# =======================================================================

if run_mode == '1':
    # =======================================================================
    # ============================ set up 0D ================================
    if Windows:
        subprocess.run(
            f'"{sv_bat}" --python -- "{gen_params0D}"',
            cwd=sv_dir,
            shell=True,
            check=True,
            text=True,
            env=env,
        )
    else:
        subprocess.run(
            [sv_py_bin, "--python", "--", gen_params0D],
            cwd=os.path.dirname(__file__),
            text=True,
            check=True
        )

    # =======================================================================
    # =========================== Run 0D ====================================
    if Windows:
        subprocess.run(
            f'"{sv_bat}" --python -- "{run_0D}"',
            cwd=sv_dir,
            shell=True,
            check=True,
            text=True,
            env=env,
        )
    else:
        subprocess.run(
            [local_py_bin, run_0D],
            cwd=os.path.dirname(__file__),
            text=True,
            check=True
        )

# =======================================================================
# ============================ extract 0D results =======================
# This runs for mode 1 (full) or mode 3 (0D extraction only)
# =======================================================================

if run_mode in ['1', '3']:
    print("\n" + "=" * 70)
    print("  [STEP] 0D Result Extraction")
    print("=" * 70)

    subprocess.run(
        [local_py_bin, extract_0d_res],
        cwd=os.path.dirname(__file__),
        text=True,
        check=True,
        env=env
    )

# =======================================================================
# ============================ Done =====================================
# =======================================================================

if run_mode == '1':
    print("\n" + "=" * 70)
    print("  MIROS workflow complete!")
    print("=" * 70 + "\n")
elif run_mode == '2':
    print("\n" + "=" * 70)
    print("  1D result extraction complete!")
    print("=" * 70 + "\n")
elif run_mode == '3':
    print("\n" + "=" * 70)
    print("  0D result extraction complete!")
    print("=" * 70 + "\n")


