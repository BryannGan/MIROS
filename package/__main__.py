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
print("    [1] Full workflow with automatic boundary condition tuning (Recommended)")
print("        -> Interactively set flow splits and pressure targets")
print("        -> Optimizer finds optimal boundary conditions automatically")
print("")
print("    [2] Full workflow with manual boundary conditions")
print("        -> User provides rcrt.dat file with pre-defined values")
print("")
print("    [3] Extract 1D results only - Skip to 1D result extraction")
print("    [4] Extract 0D results only - Skip to 0D result extraction")
print("")

run_mode = None
while run_mode not in ['1', '2', '3', '4']:
    run_mode = input("  Enter choice (1, 2, 3, or 4): ").strip()
    if run_mode not in ['1', '2', '3', '4']:
        print("  Invalid choice. Please enter 1, 2, 3, or 4.")

if run_mode in ['3', '4']:
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
tune_bc = os.path.join(pkg_dir, 'tune_bc.py')  # Automatic BC tuning module

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
# ============================ FULL WORKFLOW (Mode 1 & 2) ===============
# =======================================================================

if run_mode in ['1', '2']:
    # Set environment variable to skip manual prompts in BC tuning mode
    env_bc_tuning = env.copy()
    env_bc_tuning['MIROS_BC_TUNING_MODE'] = '1' if run_mode == '1' else '0'

    # =======================================================================
    # ============================ pre-process ==============================
    if Windows:
        subprocess.run(
            f'"{sv_bat}" --python -- "{sv_preprocess}"',
            cwd=sv_dir,
            shell=True,
            check=True,
            text=True,
            env=env_bc_tuning,
        )
    else:
        subprocess.run(
            [sv_py_bin, "--python", "--", sv_preprocess],
            cwd=os.path.dirname(__file__),
            text=True,
            check=True,
            env=env_bc_tuning
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
    # ==================== BOUNDARY CONDITION HANDLING ======================
    # =======================================================================

    if run_mode == '1':
        # Mode 1: Automatic BC tuning (Recommended)
        # First, write default RCR values (replace placeholder template)
        print("\n" + "=" * 70)
        print("  [STEP] Initializing RCR boundary conditions for tuning")
        print("=" * 70)
        sys.stdout.flush()

        # Read outlet names directly from caps folder (more robust than centerlines_outlets.dat)
        # This matches how create_rcr_bc_template() works in helper_func.py
        rcrt_file = os.path.join(master_folder, bc_filename)

        print("  -> Looking for outlet caps in: " + caps_folder)
        print("  -> Caps folder exists: " + str(os.path.exists(caps_folder)))
        sys.stdout.flush()

        if os.path.exists(caps_folder):
            # Get cap files (excluding inlet.vtp and wall.vtp)
            cap_files = [f for f in os.listdir(caps_folder)
                        if f.startswith('cap_') and f.endswith('.vtp')]
            outlet_names = sorted([os.path.splitext(f)[0] for f in cap_files])

            print("  -> Found " + str(len(outlet_names)) + " outlets: " + ", ".join(outlet_names))

            if len(outlet_names) > 0:
                # Write rcrt.dat with default numeric values
                with open(rcrt_file, 'w') as f:
                    f.write('2\n')  # RCR type
                    for name in outlet_names:
                        f.write('2\n')
                        f.write(name + '\n')
                        f.write('100.0\n')    # Default Rp
                        f.write('0.0001\n')   # Default C
                        f.write('1000.0\n')   # Default Rd
                        f.write('0.0 0.0\n')
                        f.write('1.0 0.0\n')

                print("  -> Wrote default RCR values to: " + rcrt_file)

                # Also update centerlines_outlets.dat to match (exclude inlet)
                outlets_dat_file = os.path.join(master_folder, 'centerlines_outlets.dat')
                with open(outlets_dat_file, 'w') as f:
                    for name in outlet_names:
                        f.write(name + '\n')
                print("  -> Updated centerlines_outlets.dat with " + str(len(outlet_names)) + " outlets")
                sys.stdout.flush()
            else:
                print("  [ERROR] No outlet caps found in: " + caps_folder)
                print("  [ERROR] Make sure preprocessing completed and inlet was selected.")
                sys.stdout.flush()
                sys.exit(1)
        else:
            print("  [ERROR] Caps folder not found: " + caps_folder)
            print("  [ERROR] Please run preprocessing first (sv_preprocess.py).")
            sys.stdout.flush()
            sys.exit(1)

        # Now generate 0D solver input
        print("\n" + "=" * 70)
        print("  [STEP] Setting up 0D solver (required for BC tuning)")
        print("=" * 70)

        if Windows:
            subprocess.run(
                f'"{sv_bat}" --python -- "{gen_params0D}"',
                cwd=sv_dir,
                shell=True,
                check=True,
                text=True,
                env=env_bc_tuning,
            )
        else:
            subprocess.run(
                [sv_py_bin, "--python", "--", gen_params0D],
                cwd=os.path.dirname(__file__),
                text=True,
                check=True,
                env=env_bc_tuning
            )

        # Now run BC tuning (updates 0D_solver_input.json with optimized BCs)
        print("\n" + "=" * 70)
        print("  [STEP] Automatic Boundary Condition Tuning")
        print("=" * 70 + "\n")

        subprocess.run(
            [local_py_bin, tune_bc],
            cwd=os.path.dirname(__file__),
            text=True,
            check=True,
            env=env
        )

        # Run 0D with optimized BCs
        print("\n" + "=" * 70)
        print("  [STEP] Running 0D simulation with optimized BCs")
        print("=" * 70)

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

    else:
        # Mode 2: Manual BC - prompt user to edit rcrt.dat
        rcrt_path = os.path.join(master_folder, bc_filename)
        print("\n" + "=" * 70)
        print("  [ACTION REQUIRED] Edit Boundary Conditions")
        print("=" * 70)
        print(f"\n  Please edit the RCR boundary condition file:")
        print(f"  {rcrt_path}")
        print("\n  Set appropriate Rp (proximal resistance), C (capacitance),")
        print("  and Rd (distal resistance) values for each outlet based on")
        print("  your physiological targets.")
        print("")
        input("  Press Enter when you have finished editing rcrt.dat...")

        # =======================================================================
        # ============================ 0D WORKFLOW (Mode 2) =====================
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
# This runs for mode 1, 2 (full workflows) or mode 4 (0D extraction only)
# =======================================================================

if run_mode in ['1', '2', '4']:
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
# ============================ 1D WORKFLOW (Mode 1 & 2) =================
# =======================================================================

if run_mode in ['1', '2']:
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
# This runs for mode 1, 2 (full workflows) or mode 3 (1D extraction only)
# =======================================================================

if run_mode in ['1', '2', '3']:
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
# ============================ Done =====================================
# =======================================================================

if run_mode == '1':
    print("\n" + "=" * 70)
    print("  MIROS workflow complete! (Automatic Boundary Condition Tuning)")
    print("=" * 70 + "\n")
elif run_mode == '2':
    print("\n" + "=" * 70)
    print("  MIROS workflow complete! (Manual Boundary Conditions)")
    print("=" * 70 + "\n")
elif run_mode == '3':
    print("\n" + "=" * 70)
    print("  1D result extraction complete!")
    print("=" * 70 + "\n")
elif run_mode == '4':
    print("\n" + "=" * 70)
    print("  0D result extraction complete!")
    print("=" * 70 + "\n")


