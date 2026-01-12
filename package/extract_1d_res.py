"""
extract_1d_res.py - Extract and visualize 1D simulation results

This script extracts results from the svOneDSolver output files and can:
1. Convert results to CSV format
2. Project results onto centerline geometry (.vtp)
3. Plot flow, pressure, and area waveforms
4. Display network geometry in VTK viewer

Modified by Claude: Complete rewrite with proper directory handling and visualization
"""

from pathlib import Path
import numpy as np
import os
import sys
import shutil

# ========================================================================
# ============================ Initialize  ================================

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
from package import *

# --- Helper functions for formatted output (added by Claude) ---
def print_section_header(title):
    """Print a formatted section header for better readability."""
    print("\n" + "=" * 70)
    print("  [STEP] " + title)
    print("=" * 70)

def print_status(message):
    """Print a status message with visual indicator."""
    print("  ✓ " + message)

def print_info(message):
    """Print an info message."""
    print("  → " + message)

def print_error(message):
    """Print an error message."""
    print("  [ERROR] " + message)
# --- End helper functions ---

# ========================================================================
# ============================ Setup Paths ================================

# SimVascular extraction package location
SV_SITE_PACKAGES = Path("/usr/local/sv/simvascular/2025-06-21/Python3.11/site-packages")

# Ensure site-packages is on sys.path
if str(SV_SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(SV_SITE_PACKAGES))

# Import SimVascular extraction modules
try:
    from sv_rom_extract_results.extract_results import run as extract_run
    from sv_rom_extract_results.manage import init_logging, get_logger_name, get_log_file_name
    from sv_rom_extract_results import parameters as sv_params
    from sv_rom_extract_results import solver as sv_solver
    print_status("SimVascular extraction modules loaded successfully")
except ImportError as e:
    print_error("Failed to import SimVascular extraction modules: " + str(e))
    print_info("Make sure SimVascular is installed and paths are correct")
    sys.exit(1)

# ========================================================================
# ============================ Helper Functions ===========================

def prepare_results_directory():
    """
    Ensure the results directory has all required files.
    The SimVascular extraction expects solver file and .dat files in same directory.

    Modified by Claude: Handle directory structure where solver file and results are separate
    """
    solver_file_src = os.path.join(master_folder, '1D_solver_input.in')
    solver_file_dst = os.path.join(res_folder_1D, '1D_solver_input.in')

    # Copy solver file to results directory if not already there
    if not os.path.exists(solver_file_dst):
        if os.path.exists(solver_file_src):
            shutil.copy2(solver_file_src, solver_file_dst)
            print_status("Copied solver file to results directory")
        else:
            print_error("Solver file not found: " + solver_file_src)
            return False
    else:
        print_info("Solver file already in results directory")

    # Copy 1d_model.vtp if it exists (needed for projection)
    model_file_src = os.path.join(master_folder, '1d_model.vtp')
    model_file_dst = os.path.join(res_folder_1D, '1d_model.vtp')
    if os.path.exists(model_file_src) and not os.path.exists(model_file_dst):
        shutil.copy2(model_file_src, model_file_dst)
        print_status("Copied 1d_model.vtp to results directory")

    return True


def check_results_exist():
    """
    Check if 1D simulation results exist.

    Modified by Claude: Added validation before extraction
    """
    # Check for .dat files
    dat_files = list(Path(res_folder_1D).glob("*_flow.dat"))
    if not dat_files:
        print_error("No flow result files found in: " + res_folder_1D)
        print_info("Please run the 1D simulation first")
        return False

    print_status("Found " + str(len(dat_files)) + " flow result files")
    return True


def get_cardiac_cycle_duration():
    """
    Get the cardiac cycle duration from the inflow file.

    Modified by Claude: Detect cycle duration from inflow waveform
    """
    try:
        # Read the inflow file to get cycle duration
        inflow_data = np.loadtxt(inflow_file_path)
        cycle_duration = inflow_data[-1, 0]  # Last time value = cycle duration
        print_info("Cardiac cycle duration (from inflow): " + str(cycle_duration) + " s")
        return cycle_duration
    except Exception as e:
        print_info("Could not read inflow file: " + str(e))
        return 1.0  # Default fallback


def get_simulation_time_range():
    """
    Get the time range for extraction, using the last complete cardiac cycle.

    Modified by Claude: Automatically detect cardiac cycle from inflow file
    """
    solver_file = os.path.join(res_folder_1D, '1D_solver_input.in')
    if not os.path.exists(solver_file):
        solver_file = os.path.join(master_folder, '1D_solver_input.in')

    time_step = None
    num_steps = None
    save_freq = 1

    try:
        with open(solver_file, 'r') as f:
            for line in f:
                tokens = line.split()
                if len(tokens) > 0 and tokens[0] == 'SOLVEROPTIONS':
                    time_step = float(tokens[1])
                    save_freq = int(tokens[2])
                    num_steps = int(tokens[3])
                    break

        if time_step and num_steps:
            total_sim_time = time_step * num_steps
            cycle_duration = get_cardiac_cycle_duration()

            # Calculate number of complete cycles
            num_cycles = int(total_sim_time / cycle_duration)

            # Extract the last complete cycle
            if num_cycles >= 1:
                start_time = (num_cycles - 1) * cycle_duration
                end_time = num_cycles * cycle_duration
            else:
                # Less than one cycle - extract everything
                start_time = 0
                end_time = total_sim_time

            print_info("Total simulation time: " + str(total_sim_time) + " s")
            print_info("Number of complete cycles: " + str(num_cycles))
            print_info("Extracting last cycle: " + str(round(start_time, 4)) + " to " + str(round(end_time, 4)) + " s")
            return str(start_time) + "," + str(end_time)

    except Exception as e:
        print_info("Could not read time range from solver file: " + str(e))

    # Default fallback
    return "0,100"


def _canon_cfg(cfg: dict) -> dict:
    """
    Normalize config to what extract_run(**kwargs) expects.

    Modified by Claude: Improved type handling
    """
    cfg = dict(cfg)

    # Strings for comma-separated args the script expects
    for key in ("data_names", "segments", "time_range"):
        v = cfg.get(key)
        if isinstance(v, (list, tuple)):
            cfg[key] = ",".join(map(str, v))

    # Convert booleans to expected string forms
    def _bool_to_onoff(b):
        return "on" if b else "off"

    def _bool_to_truefalse(b):
        return "true" if b else "false"

    if "display_geometry" in cfg and isinstance(cfg["display_geometry"], bool):
        cfg["display_geometry"] = _bool_to_onoff(cfg["display_geometry"])
    if "plot" in cfg and isinstance(cfg["plot"], bool):
        cfg["plot"] = _bool_to_onoff(cfg["plot"])

    for key in ("all_segments", "outlet_segments", "select_segments"):
        if key in cfg and isinstance(cfg[key], bool):
            cfg[key] = _bool_to_truefalse(cfg[key])

    return cfg


def extract_results(config: dict):
    """
    Run the SimVascular extraction pipeline.

    Modified by Claude: Added error handling and status messages
    """
    cfg = _canon_cfg(config)
    outdir = Path(cfg["output_directory"])
    outdir.mkdir(parents=True, exist_ok=True)

    # Initialize logging
    init_logging(str(outdir))

    print_info("Running extraction pipeline...")
    print_info("Output directory: " + str(outdir))

    try:
        # Run the extraction
        msg = extract_run(**cfg)
        print_status("Extraction completed")
        print_info(msg.strip())
        return True
    except Exception as e:
        print_error("Extraction failed: " + str(e))
        return False


def list_output_files():
    """
    List the generated output files.

    Modified by Claude: Added to show user what was created
    """
    print_info("Generated files:")

    # Check for various output types
    output_patterns = [
        ("*.csv", "CSV data files"),
        ("*.npy", "NumPy array files"),
        ("*.vtp", "VTK PolyData files (for ParaView)"),
        ("*.vtu", "VTK Unstructured Grid files"),
        ("*.log", "Log files"),
    ]

    for pattern, description in output_patterns:
        files = list(Path(res_folder_1D).glob(pattern))
        if files:
            print("    " + description + ":")
            for f in files:
                print("      - " + f.name)


# ========================================================================
# ============================ Main Execution =============================

if __name__ == "__main__":
    print_section_header("EXTRACT 1D RESULTS")

    # Check if results exist
    if not check_results_exist():
        sys.exit(1)

    # Prepare directory (copy solver file if needed)
    if not prepare_results_directory():
        sys.exit(1)

    # --- Configuration for 1D extraction ---
    # Modified by Claude: Fixed paths and added all options

    # Get time range from solver file
    time_range = get_simulation_time_range()

    config_1d = {
        # Required parameters
        "model_order": 1,
        "results_directory": res_folder_1D,  # Where .dat files and solver file are
        "solver_file_name": "1D_solver_input.in",
        "output_directory": res_folder_1D,
        "output_file_name": "extracted_results",  # Base name for output files
        "output_format": "csv",

        # Time range for extraction (REQUIRED - fixes NoneType error)
        # Modified by Claude: Added time_range to fix extraction error
        "time_range": time_range,

        # Data to extract (must match available .dat files)
        "data_names": "flow,pressure,area",

        # Segment selection (choose one):
        # - outlet_segments: Only outlet segments
        # - all_segments: All segments in the model
        # - segments: Specific segment names (comma-separated)
        "outlet_segments": True,
        # "all_segments": True,
        # "segments": "Group0_Seg0,Group0_Seg1",

        # Geometry files for projection (optional but recommended)
        "centerlines_file": os.path.join(master_folder, 'extracted_centerlines.vtp'),
        "walls_mesh_file": os.path.join(master_folder, 'mesh-complete', 'mesh-complete.exterior.vtp'),
        "volume_mesh_file": os.path.join(master_folder, 'mesh-complete', 'mesh-complete.mesh.vtu'),

        # Visualization options
        "plot": False,  # Set to True to show matplotlib plots
        "display_geometry": False,  # Set to True to show VTK geometry viewer
    }

    # --- Check for volume mesh availability ---
    volume_mesh_available = os.path.exists(config_1d["volume_mesh_file"])
    walls_mesh_available = os.path.exists(config_1d["walls_mesh_file"])

    if volume_mesh_available and walls_mesh_available:
        print_status("Volume mesh found - 3D projection will be available")
    else:
        print_info("Volume mesh not found - only centerline projection available")
        print_info("Run full workflow (option 1) to generate volume mesh for 3D visualization")
        config_1d.pop("volume_mesh_file", None)
        config_1d.pop("walls_mesh_file", None)

    # --- User input for visualization options ---
    # Modified by Claude: Added interactive options
    print("\n" + "-" * 70)
    print("  >>> EXTRACTION OPTIONS <<<")
    print("-" * 70)
    print("  Results directory: " + res_folder_1D)
    print("  Centerlines file: " + config_1d["centerlines_file"])
    if volume_mesh_available and walls_mesh_available:
        print("  Volume mesh: " + config_1d["volume_mesh_file"])
    print("-" * 70)

    while True:
        answer = input("  Show plots after extraction? (yes/no): ").lower()
        if answer in ["yes", "y"]:
            config_1d["plot"] = True
            break
        elif answer in ["no", "n"]:
            config_1d["plot"] = False
            break
        else:
            print("  [ERROR] Please enter 'yes' or 'no'")

    while True:
        answer = input("  Show 3D geometry viewer? (yes/no): ").lower()
        if answer in ["yes", "y"]:
            config_1d["display_geometry"] = True
            break
        elif answer in ["no", "n"]:
            config_1d["display_geometry"] = False
            break
        else:
            print("  [ERROR] Please enter 'yes' or 'no'")

    while True:
        answer = input("  Extract all segments or only outlets? (all/outlets): ").lower()
        if answer in ["all", "a"]:
            config_1d["outlet_segments"] = False
            config_1d["all_segments"] = True
            break
        elif answer in ["outlets", "outlet", "o"]:
            config_1d["outlet_segments"] = True
            config_1d.pop("all_segments", None)
            break
        else:
            print("  [ERROR] Please enter 'all' or 'outlets'")

    print("-" * 70)

    # --- Run extraction ---
    print_section_header("RUNNING EXTRACTION")

    success = extract_results(config_1d)

    if success:
        print_section_header("EXTRACTION COMPLETE")
        list_output_files()

        # Modified by Claude: Visualization instructions
        print("\n" + "-" * 70)
        print("  To visualize results in ParaView:")
        print("-" * 70)
        print("  Centerline visualization:")
        print("    - Load: " + os.path.join(res_folder_1D, "extracted_results.vtp"))
        print("    - Apply color map to flow/pressure/area fields")
        print("    - Use 'Tube' filter to visualize as 3D vessels")

        # Check if 3D results were generated
        vtu_file = os.path.join(res_folder_1D, "extracted_results.vtu")
        if os.path.exists(vtu_file):
            print("")
            print("  3D Volume visualization:")
            print("    - Load: " + vtu_file)
            print("    - Shows flow/pressure mapped to full 3D vessel geometry")

        print("-" * 70)

        # Show log file location
        log_file = os.path.join(res_folder_1D, "extract-results.log")
        if os.path.exists(log_file):
            print_info("Log file: " + log_file)
    else:
        print_error("Extraction failed. Check the log file for details.")
        sys.exit(1)
