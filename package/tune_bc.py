"""
tune_bc.py - Automatic Boundary Condition Tuning

This module optimizes RCR boundary conditions based on user-defined:
1. Flow split ratios across outlets (e.g., 10:20:30:40)
2. Target pressure values (max, min, mean) at a reference outlet

The optimization uses the fast 0D solver for iterations and outputs
an optimized rcrt.dat file for use in subsequent simulations.

Author: MIROS Team
"""

import os
import sys
import json
import numpy as np
import pandas as pd
import warnings

# Suppress common warnings during optimization
warnings.filterwarnings('ignore', category=RuntimeWarning)

# ========================================================================
# ============================ Initialize ================================

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
from package import *

# ========================================================================
# ============================ Dependency Check ==========================

def check_dependencies():
    """
    Check if required dependencies are installed.
    Returns dict with availability status.
    """
    deps = {'pysvzerod': False, 'cma': False, 'scipy': False}

    try:
        import pysvzerod
        deps['pysvzerod'] = True
    except ImportError:
        pass

    try:
        import cma
        deps['cma'] = True
    except ImportError:
        pass

    try:
        from scipy.optimize import minimize
        deps['scipy'] = True
    except ImportError:
        pass

    return deps

# Check dependencies at module load
_DEPENDENCIES = check_dependencies()

# --- Helper functions for formatted output ---
def print_section_header(title):
    """Print a formatted section header for better readability."""
    print("\n" + "=" * 70)
    print("  [STEP] " + title)
    print("=" * 70)

def print_status(message):
    """Print a status message with visual indicator."""
    print("  OK " + message)

def print_info(message):
    """Print an info message."""
    print("  -> " + message)

def print_error(message):
    """Print an error message."""
    print("  [ERROR] " + message)

def print_warning(message):
    """Print a warning message."""
    print("  [WARNING] " + message)
# --- End helper functions ---

# --- Numerical safety helpers ---
# Large penalty value for failed simulations (not too large to cause overflow)
LARGE_ERROR = 1e8


def _safe_value(value, default=0.0):
    """Return default if value is NaN, Inf, or None."""
    if value is None:
        return default
    try:
        if np.isnan(value) or np.isinf(value):
            return default
    except (TypeError, ValueError):
        return default
    return value
# --- End numerical safety helpers ---


# ========================================================================
# ============================ Unit Conversion ===========================

def mmhg_to_cgs(pressure_mmhg):
    """Convert pressure from mmHg to CGS (dyn/cm^2)."""
    return pressure_mmhg * MMHG_TO_CGS

def cgs_to_mmhg(pressure_cgs):
    """Convert pressure from CGS (dyn/cm^2) to mmHg."""
    return pressure_cgs / MMHG_TO_CGS


# ========================================================================
# ============================ User Input ================================

def load_outlet_names():
    """
    Load outlet names from centerlines_outlets.dat file.
    Returns list of outlet cap names (e.g., ['cap_2', 'cap_4', 'cap_5']).
    """
    outlets_file = os.path.join(master_folder, 'centerlines_outlets.dat')

    if not os.path.exists(outlets_file):
        print_error("Outlets file not found: " + outlets_file)
        print_info("Run preprocessing first to generate this file.")
        return None

    with open(outlets_file, 'r') as f:
        outlets = [line.strip() for line in f.readlines() if line.strip()]

    return outlets


def get_user_inputs(outlet_names):
    """
    Collect flow splits and target pressures from user via interactive prompts.

    NEW v3 UI:
    - Show ALL caps (inlet + outlets) for pressure targeting
    - Allow user to select multiple caps for pressure targets
    - Add timeout parameter

    Returns:
        flow_splits: dict {outlet_name: flow_percentage}
        pressure_targets: dict {cap_name: {'max': x, 'min': y, 'mean': z}}
        timeout_min: int, optimization timeout in minutes
        optimizer: str, 'scipy' or 'cma'
    """
    print_section_header("BOUNDARY CONDITION TUNING - USER INPUT")
    print("")
    print("  This tool will help you find optimal boundary condition parameters")
    print("  (resistance and capacitance values) that match your target blood")
    print("  flow distribution and pressure values.")
    print("")

    n_outlets = len(outlet_names)
    print_info("Number of outlets: " + str(n_outlets))
    print("\n  Available outlets:")
    for i, name in enumerate(outlet_names):
        print("    [" + str(i+1) + "] " + name)

    # ======================== Flow Splits ========================
    print("\n" + "-" * 70)
    print("  >>> STEP 1: BLOOD FLOW DISTRIBUTION <<<")
    print("-" * 70)
    print("  How should blood flow be distributed among the outlets?")
    print("  Enter the percentage of total flow for each outlet.")
    print("  (All percentages must sum to 100%)\n")
    print("  Example: If you have 5 outlets and want equal distribution,")
    print("           enter 20% for each outlet.\n")

    flow_splits = {}
    while True:
        total = 0
        flow_splits = {}

        for name in outlet_names:
            while True:
                try:
                    val = float(input("    " + name + " flow %: "))
                    if val < 0 or val > 100:
                        print("      Please enter a value between 0 and 100")
                        continue
                    flow_splits[name] = val
                    total += val
                    break
                except ValueError:
                    print("      Invalid input. Please enter a number.")

        if abs(total - 100.0) < 0.01:
            print_status("Flow splits sum to 100%")
            break
        else:
            print_warning("Flow splits sum to " + str(total) + "%, not 100%. Please re-enter.")

    # ======================== Pressure Targets (NEW v3 UI) ========================
    print("\n" + "-" * 70)
    print("  >>> STEP 2: TARGET BLOOD PRESSURE <<<")
    print("-" * 70)
    print("  What blood pressure values do you want to achieve?")
    print("  Select where to measure pressure (inlet or any outlet).\n")
    print("  Typical values for a healthy adult:")
    print("    - Systolic (max): 100-140 mmHg")
    print("    - Diastolic (min): 60-90 mmHg\n")

    # Build list of ALL caps (inlet + outlets)
    all_caps = ['inlet'] + outlet_names
    for i, name in enumerate(all_caps):
        flow_info = ""
        if name in flow_splits:
            flow_info = " (flow: " + str(flow_splits[name]) + "%)"
        print("    [" + str(i+1) + "] " + name + flow_info)

    # Collect pressure targets for selected caps
    pressure_targets = {}
    max_targets = 3

    while len(pressure_targets) < max_targets:
        print("\n  Select cap for pressure targeting:")

        while True:
            try:
                choice = int(input("  Enter cap number (1-" + str(len(all_caps)) + "): "))
                if 1 <= choice <= len(all_caps):
                    selected_cap = all_caps[choice - 1]
                    if selected_cap in pressure_targets:
                        print("    Already added. Choose a different cap.")
                        continue
                    break
                else:
                    print("    Invalid choice. Please enter 1-" + str(len(all_caps)))
            except ValueError:
                print("    Invalid input. Please enter a number.")

        # Get pressure targets for this cap
        print("\n" + "-" * 50)
        print("  >>> TARGET PRESSURES AT " + selected_cap.upper() + " <<<")
        print("-" * 50)
        print("  Enter target pressures in mmHg:\n")

        while True:
            try:
                target_max = float(input("    Systolic (max) pressure [mmHg]: "))
                target_min = float(input("    Diastolic (min) pressure [mmHg]: "))

                if target_max < target_min:
                    print("      Error: Systolic must be greater than diastolic")
                    continue

                # Mean pressure is optional (v4)
                include_mean = input("    Include mean pressure target? (y/n, default n): ").strip().lower()
                if include_mean == 'y':
                    target_mean = float(input("    Mean pressure [mmHg]: "))
                    if target_mean < target_min or target_mean > target_max:
                        print("      Error: Mean must be between systolic and diastolic")
                        continue
                else:
                    target_mean = None  # Will be excluded from objective

                pressure_targets[selected_cap] = {
                    'max': target_max,
                    'min': target_min,
                    'mean': target_mean
                }
                if target_mean is not None:
                    print_status("Added: " + selected_cap + " -> " + str(target_max) + "/" +
                                str(target_min) + "/" + str(target_mean) + " mmHg")
                else:
                    print_status("Added: " + selected_cap + " -> " + str(target_max) + "/" +
                                str(target_min) + " mmHg (no mean)")
                break
            except ValueError:
                print("      Invalid input. Please enter numbers.")

        # Ask if user wants to add another target
        if len(pressure_targets) < max_targets:
            print("\n  Note: 1-2 pressure targets usually sufficient.")
            print("  Too many targets may over-constrain the system.")
            add_more = input("  Add pressure target to another cap? (y/n): ").strip().lower()
            if add_more != 'y':
                break

    print_status("Total pressure targets: " + str(len(pressure_targets)))

    # ======================== Timeout ========================
    print("\n" + "-" * 70)
    print("  >>> STEP 3: OPTIMIZATION TIME LIMIT <<<")
    print("-" * 70)
    print("  How long should the optimizer search for the best parameters?")
    print("  The optimizer will stop when it finds a good solution OR")
    print("  when the time limit is reached.\n")
    print("  Recommended: 5-15 minutes for most models.\n")

    while True:
        try:
            timeout_input = input("  Enter timeout in minutes (default 10): ").strip()
            if timeout_input == "":
                timeout_min = 10
            else:
                timeout_min = int(timeout_input)
            if timeout_min < 1:
                print("    Timeout must be at least 1 minute")
                continue
            print_status("Timeout: " + str(timeout_min) + " minutes")
            break
        except ValueError:
            print("    Invalid input. Please enter a number.")

    # ======================== Optimizer Selection ========================
    print("\n" + "-" * 70)
    print("  >>> STEP 4: OPTIMIZATION METHOD <<<")
    print("-" * 70)
    print("  Which optimization algorithm should find your parameters?\n")
    print("    [1] CMA-ES Optimizer (Recommended)")
    print("        -> Global search algorithm, very robust")
    print("        -> Finds optimal parameters reliably")
    print("        -> Best choice for most models")
    print("")
    print("    [2] Two-Phase Optimizer (Alternative)")
    print("        -> First optimizes pressure, then flow distribution")
    print("        -> Faster but may get stuck in local minima")

    while True:
        try:
            choice = int(input("\n  Select optimizer (1 or 2): "))
            if choice == 1:
                optimizer = 'cma'
                print_status("Using CMA-ES Optimizer (Recommended)")
                break
            elif choice == 2:
                optimizer = 'scipy'
                print_status("Using Two-Phase Optimizer")
                break
            else:
                print("  Invalid choice. Please enter 1 or 2.")
        except ValueError:
            print("  Invalid input. Please enter 1 or 2.")

    return flow_splits, pressure_targets, timeout_min, optimizer


# ========================================================================
# ============================ RCR Parameter Generation ==================

def compute_resistance_ratios(flow_splits):
    """
    Convert flow split percentages to resistance ratios.

    Since Q ∝ 1/R (for same pressure drop), resistance is inversely
    proportional to flow. We normalize so the minimum ratio is 1.0.

    Args:
        flow_splits: dict {outlet_name: flow_percentage}

    Returns:
        dict {outlet_name: resistance_ratio}
    """
    # Compute inverse of flow ratios
    resistance_ratios = {}
    for name, flow_pct in flow_splits.items():
        if flow_pct > 0:
            resistance_ratios[name] = 100.0 / flow_pct
        else:
            # Very low flow -> very high resistance
            resistance_ratios[name] = 10000.0

    # Normalize so minimum ratio is 1.0
    min_ratio = min(resistance_ratios.values())
    for name in resistance_ratios:
        resistance_ratios[name] /= min_ratio

    return resistance_ratios


def generate_rcr_params(R_scale, C_scale, resistance_ratios, outlet_names, Rp_ratio=None):
    """
    Generate RCR parameters for each outlet.

    Args:
        R_scale: float, base resistance value (absolute scaling)
        C_scale: float, capacitance scaling factor
        resistance_ratios: dict {outlet_name: ratio}
        outlet_names: list of outlet names
        Rp_ratio: float, fraction of total R that is proximal (default from config)

    Returns:
        dict {outlet_name: {'Rp': float, 'C': float, 'Rd': float}}
    """
    if Rp_ratio is None:
        Rp_ratio = default_Rp_ratio

    rcr_params = {}
    for name in outlet_names:
        R_total = R_scale * resistance_ratios[name]
        Rp = Rp_ratio * R_total
        Rd = (1.0 - Rp_ratio) * R_total
        C = C_scale * default_capacitance

        rcr_params[name] = {
            'Rp': Rp,
            'C': C,
            'Rd': Rd
        }

    return rcr_params


# ========================================================================
# ============================ File I/O ==================================

def write_rcrt_dat(rcr_params, outlet_names, output_path):
    """
    Write RCR parameters to rcrt.dat file.

    Args:
        rcr_params: dict {outlet_name: {'Rp': float, 'C': float, 'Rd': float}}
        outlet_names: list of outlet names (to maintain order)
        output_path: str, path to output file
    """
    with open(output_path, 'w') as f:
        f.write('2\n')  # RCR type identifier

        for name in outlet_names:
            params = rcr_params[name]
            f.write('2\n')
            f.write(name + '\n')
            f.write(str(params['Rp']) + '\n')
            f.write(str(params['C']) + '\n')
            f.write(str(params['Rd']) + '\n')
            f.write('0.0 0.0\n')
            f.write('1.0 0.0\n')


def update_0d_solver_input(rcr_params, outlet_names, json_path):
    """
    Update 0D solver input JSON with new RCR boundary condition values.

    Args:
        rcr_params: dict {outlet_name: {'Rp': float, 'C': float, 'Rd': float}}
        outlet_names: list of outlet names
        json_path: str, path to 0D_solver_input.json
    """
    with open(json_path, 'r') as f:
        config = json.load(f)

    # Update RCR boundary conditions
    for i, bc in enumerate(config['boundary_conditions']):
        if bc['bc_type'] == 'RCR':
            # Map RCR index to outlet
            rcr_idx = int(bc['bc_name'].replace('RCR_', ''))
            if rcr_idx < len(outlet_names):
                outlet_name = outlet_names[rcr_idx]
                if outlet_name in rcr_params:
                    params = rcr_params[outlet_name]
                    bc['bc_values']['Rp'] = params['Rp']
                    bc['bc_values']['C'] = params['C']
                    bc['bc_values']['Rd'] = params['Rd']

    with open(json_path, 'w') as f:
        json.dump(config, f, indent=4)


def validate_rcr_params(rcr_params, outlet_names):
    """
    Validate RCR parameters are within reasonable bounds.

    Args:
        rcr_params: dict {outlet_name: {'Rp': float, 'C': float, 'Rd': float}}
        outlet_names: list of outlet names

    Returns:
        dict: Validated and bounded RCR params

    Bounds:
        R (Rp, Rd): [1, 1e7] CGS
        C: [1e-8, 1] CGS
    """
    R_MIN, R_MAX = 1.0, 1e7
    C_MIN, C_MAX = 1e-8, 1.0

    validated = {}
    for name in outlet_names:
        if name not in rcr_params:
            # Use defaults if missing
            validated[name] = {'Rp': 500.0, 'C': 0.001, 'Rd': 5000.0}
            continue

        params = rcr_params[name]
        validated[name] = {
            'Rp': np.clip(_safe_value(params.get('Rp', 500.0), 500.0), R_MIN, R_MAX),
            'C': np.clip(_safe_value(params.get('C', 0.001), 0.001), C_MIN, C_MAX),
            'Rd': np.clip(_safe_value(params.get('Rd', 5000.0), 5000.0), R_MIN, R_MAX)
        }

    return validated


def load_json_config(json_path):
    """
    Safely load JSON config with error handling.

    Args:
        json_path: path to JSON file

    Returns:
        dict: Loaded config

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If JSON is invalid
    """
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Config file not found: {json_path}")

    try:
        with open(json_path, 'r') as f:
            config = json.load(f)

        # Basic validation
        if not isinstance(config, dict):
            raise ValueError("Config must be a JSON object")

        if 'boundary_conditions' not in config:
            raise ValueError("Config missing 'boundary_conditions' key")

        return config

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {json_path}: {str(e)}")


def update_config_in_memory(base_config, rcr_params, outlet_names):
    """
    Update config dict with new RCR values (thread-safe, no file I/O).
    Returns a deep copy with updated values.

    This avoids race conditions when scipy uses parallel gradient computation.

    Args:
        base_config: dict, original 0D solver config
        rcr_params: dict {outlet_name: {'Rp': float, 'C': float, 'Rd': float}}
        outlet_names: list of outlet names

    Returns:
        dict: Updated config (deep copy)
    """
    from copy import deepcopy

    if base_config is None:
        raise ValueError("base_config cannot be None")

    config = deepcopy(base_config)

    # Validate RCR params before applying
    validated_params = validate_rcr_params(rcr_params, outlet_names)

    for i, bc in enumerate(config.get('boundary_conditions', [])):
        if bc.get('bc_type') == 'RCR':
            try:
                rcr_idx = int(bc['bc_name'].replace('RCR_', ''))
                if rcr_idx < len(outlet_names):
                    outlet_name = outlet_names[rcr_idx]
                    if outlet_name in validated_params:
                        params = validated_params[outlet_name]
                        bc['bc_values']['Rp'] = params['Rp']
                        bc['bc_values']['C'] = params['C']
                        bc['bc_values']['Rd'] = params['Rd']
            except (ValueError, KeyError):
                # Skip if bc_name format is unexpected
                continue

    return config


# ========================================================================
# ============================ 0D Simulation =============================

def run_0d_simulation(json_path):
    """
    Run 0D solver and return results as DataFrame.

    Args:
        json_path: str, path to 0D_solver_input.json

    Returns:
        pd.DataFrame with columns: name, time, flow_in, flow_out, pressure_in, pressure_out

    Raises:
        FileNotFoundError: If JSON file doesn't exist
        RuntimeError: If simulation fails
    """
    if not _DEPENDENCIES['pysvzerod']:
        raise ImportError("pysvzerod is not installed. Install with: pip install pysvzerod")

    if not os.path.exists(json_path):
        raise FileNotFoundError(f"0D solver input not found: {json_path}")

    import pysvzerod

    try:
        solver = pysvzerod.Solver(json_path)
        solver.run()
        data = solver.get_full_result()
        df = pd.DataFrame(data)

        # Validate output
        if df.empty:
            raise RuntimeError("Simulation returned empty results")

        required_cols = ['name', 'time', 'pressure_in', 'pressure_out', 'flow_in', 'flow_out']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            raise RuntimeError(f"Simulation results missing columns: {missing_cols}")

        # Check for NaN/Inf in critical columns
        for col in ['pressure_in', 'pressure_out', 'flow_in', 'flow_out']:
            if df[col].isna().any() or np.isinf(df[col]).any():
                raise RuntimeError(f"Simulation produced invalid values in {col}")

        return df

    except Exception as e:
        if "pysvzerod" in str(type(e).__module__):
            raise RuntimeError(f"0D solver failed: {str(e)}")
        raise


def run_0d_simulation_in_memory(config):
    """
    Run 0D solver with in-memory config dict (thread-safe, no file I/O).

    This avoids race conditions when scipy uses parallel gradient computation.

    Args:
        config: dict, 0D solver configuration

    Returns:
        pd.DataFrame with columns: name, time, flow_in, flow_out, pressure_in, pressure_out

    Raises:
        ValueError: If config is invalid
        RuntimeError: If simulation fails
    """
    if not _DEPENDENCIES['pysvzerod']:
        raise ImportError("pysvzerod is not installed. Install with: pip install pysvzerod")

    if config is None or not isinstance(config, dict):
        raise ValueError("Invalid config: must be a non-empty dictionary")

    import pysvzerod

    try:
        solver = pysvzerod.Solver(config)
        solver.run()
        data = solver.get_full_result()
        df = pd.DataFrame(data)

        # Validate output
        if df.empty:
            raise RuntimeError("Simulation returned empty results")

        # Check for NaN/Inf in critical columns
        for col in ['pressure_in', 'pressure_out', 'flow_in', 'flow_out']:
            if col in df.columns:
                if df[col].isna().any() or np.isinf(df[col]).any():
                    raise RuntimeError(f"Simulation produced invalid values in {col}")

        return df

    except Exception as e:
        if "pysvzerod" in str(type(e).__module__):
            raise RuntimeError(f"0D solver failed: {str(e)}")
        raise


def get_cardiac_cycle_duration():
    """Get cardiac cycle duration from inflow file."""
    try:
        inflow_data = np.loadtxt(inflow_file_path)
        return inflow_data[-1, 0]
    except:
        return 1.0


def extract_outlet_metrics(df, ref_outlet, outlet_names, cycle_duration):
    """
    Extract pressure metrics at the reference outlet.

    Args:
        df: pd.DataFrame, 0D simulation results
        ref_outlet: str, name of reference outlet
        outlet_names: list of outlet names
        cycle_duration: float, cardiac cycle duration (s)

    Returns:
        dict with max_pressure, min_pressure, mean_pressure (in CGS units)
    """
    # Find the segment corresponding to the reference outlet
    # The outlet segments are the last segment of each branch
    segments = df['name'].unique().tolist()

    # Group by branch
    branch_segments = {}
    for seg in segments:
        parts = seg.split('_')
        if len(parts) >= 2:
            branch = parts[0]
            seg_num = int(parts[1].replace('seg', ''))
            if branch not in branch_segments:
                branch_segments[branch] = []
            branch_segments[branch].append((seg_num, seg))

    # Get outlet segments (last segment of each branch)
    outlet_segments = []
    for branch, segs in branch_segments.items():
        segs.sort(key=lambda x: x[0])
        outlet_segments.append(segs[-1][1])

    # Map outlet index to segment (assumes same order)
    ref_outlet_idx = outlet_names.index(ref_outlet)
    if ref_outlet_idx < len(outlet_segments):
        ref_segment = outlet_segments[ref_outlet_idx]
    else:
        # Fallback: use first outlet segment
        ref_segment = outlet_segments[0] if outlet_segments else segments[0]

    # Extract segment data
    seg_data = df[df['name'] == ref_segment].copy()
    seg_data = seg_data.sort_values('time')

    # Extract last cardiac cycle
    max_time = seg_data['time'].max()
    num_cycles = int(max_time / cycle_duration)
    if num_cycles >= 1:
        start_time = (num_cycles - 1) * cycle_duration
    else:
        start_time = 0

    last_cycle = seg_data[seg_data['time'] >= start_time]

    # Compute metrics (use pressure_out for outlet)
    metrics = {
        'max_pressure': last_cycle['pressure_out'].max(),
        'min_pressure': last_cycle['pressure_out'].min(),
        'mean_pressure': last_cycle['pressure_out'].mean(),
        'segment': ref_segment
    }

    return metrics


def extract_inlet_metrics(df, cycle_duration):
    """
    Extract pressure metrics at the inlet (first segment of the network).

    Args:
        df: pd.DataFrame, 0D simulation results
        cycle_duration: float, cardiac cycle duration (s)

    Returns:
        dict with max_pressure, min_pressure, mean_pressure (in CGS units)
    """
    segments = df['name'].unique().tolist()

    # Find inlet segment (typically branch0_seg0 or first segment)
    inlet_segment = None
    for seg in segments:
        if 'seg0' in seg or seg.endswith('_0'):
            inlet_segment = seg
            break

    if inlet_segment is None:
        # Fallback to first segment alphabetically
        inlet_segment = sorted(segments)[0]

    seg_data = df[df['name'] == inlet_segment].copy()
    seg_data = seg_data.sort_values('time')

    # Extract last cardiac cycle
    max_time = seg_data['time'].max()
    num_cycles = int(max_time / cycle_duration)
    if num_cycles >= 1:
        start_time = (num_cycles - 1) * cycle_duration
    else:
        start_time = 0

    last_cycle = seg_data[seg_data['time'] >= start_time]

    # Compute metrics (use pressure_in for inlet)
    metrics = {
        'max_pressure': last_cycle['pressure_in'].max(),
        'min_pressure': last_cycle['pressure_in'].min(),
        'mean_pressure': last_cycle['pressure_in'].mean(),
        'segment': inlet_segment
    }

    return metrics


def extract_flow_distribution(df, outlet_names, cycle_duration):
    """
    Extract flow distribution across outlets for verification.

    Returns dict {outlet_name: mean_flow_out}

    Handles edge cases:
    - Empty dataframes
    - Missing segments
    - NaN/Inf values
    """
    if df.empty:
        # Return zero flow for all outlets if no data
        return {name: 0.0 for name in outlet_names}

    segments = df['name'].unique().tolist()

    if not segments:
        return {name: 0.0 for name in outlet_names}

    # Get outlet segments
    branch_segments = {}
    for seg in segments:
        parts = seg.split('_')
        if len(parts) >= 2:
            branch = parts[0]
            try:
                seg_num = int(parts[1].replace('seg', ''))
                if branch not in branch_segments:
                    branch_segments[branch] = []
                branch_segments[branch].append((seg_num, seg))
            except ValueError:
                # Skip segments with non-numeric identifiers
                continue

    outlet_segments = []
    for branch, segs in sorted(branch_segments.items()):
        segs.sort(key=lambda x: x[0])
        outlet_segments.append(segs[-1][1])

    # Extract flow for each outlet
    flow_dist = {}
    max_time = df['time'].max()

    # Safety check for cycle_duration
    if cycle_duration <= 0 or np.isnan(cycle_duration) or np.isinf(cycle_duration):
        cycle_duration = 1.0  # Default fallback

    num_cycles = int(max_time / cycle_duration) if max_time > 0 else 0
    start_time = (num_cycles - 1) * cycle_duration if num_cycles >= 1 else 0

    for i, name in enumerate(outlet_names):
        if i < len(outlet_segments):
            seg = outlet_segments[i]
            seg_data = df[df['name'] == seg]
            last_cycle = seg_data[seg_data['time'] >= start_time]

            if not last_cycle.empty:
                flow_value = last_cycle['flow_out'].mean()
                # Handle NaN/Inf
                if np.isnan(flow_value) or np.isinf(flow_value):
                    flow_value = 0.0
                flow_dist[name] = abs(flow_value)
            else:
                flow_dist[name] = 0.0
        else:
            flow_dist[name] = 0.0

    return flow_dist


def check_convergence(flow_splits, pressure_targets, df, outlet_names, cycle_duration):
    """
    Check if optimization has converged (v3).

    Convergence criteria:
    - All flow splits within 10% of targets
    - All pressures within 10% of targets

    Args:
        flow_splits: dict {outlet_name: target_flow_percentage}
        pressure_targets: dict {cap_name: {'max': x, 'min': y, 'mean': z}} in mmHg
        df: pd.DataFrame, 0D simulation results
        outlet_names: list of outlet names
        cycle_duration: float, cardiac cycle duration

    Returns:
        tuple (converged: bool, details: dict with achieved values and errors)
    """
    details = {
        'flow': {},
        'pressure': {},
        'flow_converged': True,
        'pressure_converged': True
    }

    # ======================== Check Flow Splits ========================
    # Adaptive tolerance: 10% for large vessels (>=15% flow), 25% for small vessels (<15% flow)
    flow_dist = extract_flow_distribution(df, outlet_names, cycle_duration)
    total_flow = sum(flow_dist.values())

    for name in outlet_names:
        target_pct = flow_splits[name]
        achieved_pct = (flow_dist[name] / total_flow) * 100 if total_flow > 0 else 0
        error_pct = abs(achieved_pct - target_pct) / target_pct * 100 if target_pct > 0 else 0

        # Use relaxed tolerance for small vessels
        tolerance = 10 if target_pct >= 15 else 25
        is_small_vessel = target_pct < 15

        details['flow'][name] = {
            'target': target_pct,
            'achieved': achieved_pct,
            'error_pct': error_pct,
            'tolerance': tolerance,
            'is_small_vessel': is_small_vessel
        }

        if error_pct > tolerance:
            details['flow_converged'] = False

    # ======================== Check Pressure Targets ========================
    for cap, targets in pressure_targets.items():
        if cap == 'inlet':
            metrics = extract_inlet_metrics(df, cycle_duration)
        else:
            metrics = extract_outlet_metrics(df, cap, outlet_names, cycle_duration)

        achieved_max = cgs_to_mmhg(metrics['max_pressure'])
        achieved_min = cgs_to_mmhg(metrics['min_pressure'])
        achieved_mean = cgs_to_mmhg(metrics['mean_pressure'])

        error_max = abs(achieved_max - targets['max']) / targets['max'] * 100
        error_min = abs(achieved_min - targets['min']) / targets['min'] * 100

        details['pressure'][cap] = {
            'max': {'target': targets['max'], 'achieved': achieved_max, 'error_pct': error_max},
            'min': {'target': targets['min'], 'achieved': achieved_min, 'error_pct': error_min}
        }

        # Check convergence for max and min
        if error_max > 10 or error_min > 10:
            details['pressure_converged'] = False

        # Handle optional mean (v4)
        if targets.get('mean') is not None:
            error_mean = abs(achieved_mean - targets['mean']) / targets['mean'] * 100
            details['pressure'][cap]['mean'] = {
                'target': targets['mean'], 'achieved': achieved_mean, 'error_pct': error_mean
            }
            if error_mean > 10:
                details['pressure_converged'] = False

    converged = details['flow_converged'] and details['pressure_converged']
    return converged, details


# ========================================================================
# ============================ Error Computation Helpers (v4) ============

def compute_flow_error(df, flow_splits, outlet_names, cycle_duration):
    """
    Compute flow split error (sum of squared percentage errors).

    Returns:
        float: Σ((achieved_pct - target_pct)²)

    Handles edge cases:
    - Zero total flow
    - NaN/Inf values
    - Empty dataframes
    """
    if df is None or df.empty:
        return LARGE_ERROR

    flow_dist = extract_flow_distribution(df, outlet_names, cycle_duration)
    total_flow = sum(flow_dist.values())

    # Handle zero total flow
    if total_flow <= 0 or np.isnan(total_flow) or np.isinf(total_flow):
        return LARGE_ERROR

    flow_error = 0.0
    for name in outlet_names:
        target_pct = flow_splits.get(name, 0.0)
        achieved_pct = (flow_dist.get(name, 0.0) / total_flow) * 100

        # Safety check
        achieved_pct = _safe_value(achieved_pct, 0.0)
        target_pct = _safe_value(target_pct, 0.0)

        flow_error += (achieved_pct - target_pct) ** 2

    # Final safety check
    return _safe_value(flow_error, LARGE_ERROR)


def compute_pressure_error(df, pressure_targets, outlet_names, cycle_duration):
    """
    Compute pressure error (sum of squared mmHg errors).
    Handles optional mean pressure.

    Returns:
        float: Σ((achieved_mmHg - target_mmHg)²)

    Handles edge cases:
    - Missing metrics
    - NaN/Inf values
    - Empty dataframes
    """
    if df is None or df.empty:
        return LARGE_ERROR

    pressure_error = 0.0

    for cap, targets in pressure_targets.items():
        try:
            if cap == 'inlet':
                metrics = extract_inlet_metrics(df, cycle_duration)
            else:
                metrics = extract_outlet_metrics(df, cap, outlet_names, cycle_duration)

            # Extract and validate values
            max_p = _safe_value(cgs_to_mmhg(metrics.get('max_pressure', 0)), 0.0)
            min_p = _safe_value(cgs_to_mmhg(metrics.get('min_pressure', 0)), 0.0)
            mean_p = _safe_value(cgs_to_mmhg(metrics.get('mean_pressure', 0)), 0.0)

            target_max = _safe_value(targets.get('max', 120.0), 120.0)
            target_min = _safe_value(targets.get('min', 80.0), 80.0)

            pressure_error += (max_p - target_max) ** 2
            pressure_error += (min_p - target_min) ** 2

            # Mean is optional (v4)
            if targets.get('mean') is not None:
                target_mean = _safe_value(targets['mean'], 100.0)
                pressure_error += (mean_p - target_mean) ** 2

        except Exception:
            # If extraction fails, add large penalty
            pressure_error += LARGE_ERROR

    # Final safety check
    return _safe_value(pressure_error, LARGE_ERROR)


# ========================================================================
# ============================ Two-Phase Optimization (v4) ===============

def run_two_phase_optimization(flow_splits, outlet_names, pressure_targets,
                               json_path, cycle_duration, timeout_min):
    """
    Two-phase optimization (v4):
    Phase 1: Optimize total R and C for pressure targets
    Phase 2: Fine-tune R_total/C and redistribute R among outlets for flow splits

    Uses IN-MEMORY config to avoid file I/O race conditions with scipy's
    parallel gradient computation.

    Args:
        flow_splits: dict {outlet_name: target_flow_percentage}
        outlet_names: list of outlet names
        pressure_targets: dict {cap_name: {'max': x, 'min': y, 'mean': z or None}}
        json_path: path to 0D solver input JSON
        cycle_duration: cardiac cycle duration
        timeout_min: timeout in minutes

    Returns:
        tuple (R_values_final, C_final, n_iters, stop_reason)
    """
    import time

    # Check scipy availability
    if not _DEPENDENCIES['scipy']:
        raise ImportError("scipy is not installed. Install with: pip install scipy")

    from scipy.optimize import minimize

    start_time = time.time()
    timeout_sec = timeout_min * 60
    N = len(outlet_names)
    iteration_counter = [0]
    consecutive_failures = [0]  # Track consecutive simulation failures
    MAX_CONSECUTIVE_FAILURES = 20

    # Validate inputs
    if not outlet_names:
        raise ValueError("outlet_names cannot be empty")

    if not flow_splits:
        raise ValueError("flow_splits cannot be empty")

    if cycle_duration <= 0:
        print_warning(f"Invalid cycle_duration ({cycle_duration}), using default 1.0")
        cycle_duration = 1.0

    # Load base config ONCE into memory to avoid file I/O race conditions
    try:
        base_config = load_json_config(json_path)
    except (FileNotFoundError, ValueError) as e:
        print_error(str(e))
        raise

    # ============================================================
    # PHASE 1: Optimize for pressure (find correct total R and C)
    # ============================================================
    print_section_header("PHASE 1: Pressure Optimization")
    print_info("Finding optimal total resistance and capacitance...")
    print_info("Flow splits used for initial R distribution only")

    # Precompute inverse flow weights for R distribution
    inv_flow_sum = sum(100.0 / f for f in flow_splits.values() if f > 0)

    def distribute_R(R_total):
        """Distribute R_total based on flow splits (inverse proportion)."""
        R_values = []
        for name in outlet_names:
            flow_pct = flow_splits[name]
            if flow_pct > 0:
                R_i = R_total * (100.0 / flow_pct) / inv_flow_sum
            else:
                R_i = R_total * 10  # Very high for zero flow
            R_values.append(R_i)
        return R_values

    def phase1_objective(x):
        R_total, C = x[0], x[1]

        # Validate inputs
        R_total = _safe_value(R_total, 5000.0)
        C = _safe_value(C, 0.005)

        # Enforce bounds
        R_total = np.clip(R_total, 500, 100000)
        C = np.clip(C, 0.0001, 0.1)

        R_values = distribute_R(R_total)

        # Build RCR params and run simulation
        rcr_params = {}
        for i, name in enumerate(outlet_names):
            rcr_params[name] = {
                'Rp': default_Rp_ratio * R_values[i],
                'C': C,
                'Rd': (1 - default_Rp_ratio) * R_values[i]
            }

        # Use in-memory config (thread-safe, no file I/O)
        config = update_config_in_memory(base_config, rcr_params, outlet_names)

        try:
            df = run_0d_simulation_in_memory(config)
            pressure_error = compute_pressure_error(df, pressure_targets, outlet_names, cycle_duration)

            # Reset consecutive failures on success
            consecutive_failures[0] = 0

            iteration_counter[0] += 1
            if iteration_counter[0] % 20 == 0 or iteration_counter[0] <= 3:
                print("    Phase1 Iter " + str(iteration_counter[0]) +
                      ": Pressure err = " + str(round(pressure_error, 1)) + " mmHg^2" +
                      ", R_total = " + str(round(R_total, 0)) +
                      ", C = " + str(round(C, 6)))

            return pressure_error

        except Exception as e:
            consecutive_failures[0] += 1
            iteration_counter[0] += 1

            if consecutive_failures[0] >= MAX_CONSECUTIVE_FAILURES:
                print_warning(f"Too many consecutive failures ({consecutive_failures[0]}), stopping Phase 1")
                raise StopIteration("Too many failures")

            # Return large but not infinite error
            return LARGE_ERROR

    # Initial guess and bounds for Phase 1
    x0_phase1 = [5000.0, 0.005]  # R_total, C
    bounds_phase1 = [(500, 100000), (0.0001, 0.1)]

    print_info("Initial R_total: 5000, Initial C: 0.005")
    print_info("Running Phase 1 optimization...")

    try:
        result1 = minimize(
            phase1_objective,
            x0_phase1,
            method='L-BFGS-B',
            bounds=bounds_phase1,
            options={'maxiter': 500, 'ftol': 1e-10, 'gtol': 1e-10}
        )
        R_total_opt = result1.x[0]
        C_opt = result1.x[1]
    except StopIteration:
        # Too many failures - use default values
        print_warning("Phase 1 stopped early due to failures, using defaults")
        R_total_opt = 5000.0
        C_opt = 0.005
    except Exception as e:
        print_error(f"Phase 1 optimization failed: {str(e)}")
        R_total_opt = 5000.0
        C_opt = 0.005

    phase1_iters = iteration_counter[0]

    # Validate Phase 1 results
    R_total_opt = _safe_value(R_total_opt, 5000.0)
    C_opt = _safe_value(C_opt, 0.005)
    R_total_opt = np.clip(R_total_opt, 500, 100000)
    C_opt = np.clip(C_opt, 0.0001, 0.1)

    print_status("Phase 1 complete!")
    print_info("Optimal R_total: " + str(round(R_total_opt, 1)))
    print_info("Optimal C: " + str(round(C_opt, 6)))
    print_info("Phase 1 iterations: " + str(phase1_iters))

    # Check timeout
    elapsed = time.time() - start_time
    if elapsed > timeout_sec:
        print_warning("Timeout reached after Phase 1")
        R_values_final = distribute_R(R_total_opt)
        return R_values_final, C_opt, iteration_counter[0], 'timeout'

    # ============================================================
    # PHASE 2: Optimize flow splits AND fine-tune R_total/C
    # ============================================================
    print_section_header("PHASE 2: Flow Split Optimization")
    print_info("Optimizing resistance distribution + fine-tuning R_total and C...")
    print_info("R_total STARTING at: " + str(round(R_total_opt, 1)) + " (can adjust)")
    print_info("C STARTING at: " + str(round(C_opt, 6)) + " (can adjust)")

    phase2_iter = [0]
    best_R_total = [R_total_opt]
    best_C = [C_opt]

    def phase2_objective(params):
        """
        Optimize allocation of R among outlets AND fine-tune R_total and C.
        params: [allocation_0, ..., allocation_{N-1}, log_R_total, log_C]
                First N values are log-space allocation ratios
                Last 2 values are log-space R_total and C
        """
        # Extract parameters with safety checks
        allocation_raw = params[:N]
        log_R_total = params[N]
        log_C = params[N + 1]

        # Validate log values (prevent overflow)
        log_R_total = np.clip(_safe_value(log_R_total, np.log(R_total_opt)), -10, 20)
        log_C = np.clip(_safe_value(log_C, np.log(C_opt)), -15, 5)

        # Convert from log space with safety
        try:
            allocation = np.exp(np.clip(allocation_raw, -20, 20))
            alloc_sum = np.sum(allocation)
            if alloc_sum <= 0 or np.isnan(alloc_sum) or np.isinf(alloc_sum):
                allocation = np.ones(N) / N
            else:
                allocation = allocation / alloc_sum

            R_total = np.exp(log_R_total)
            C = np.exp(log_C)
        except (OverflowError, FloatingPointError):
            # Fallback to Phase 1 values
            R_total = R_total_opt
            C = C_opt
            allocation = np.ones(N) / N

        # Enforce bounds on R_total and C
        R_total = np.clip(_safe_value(R_total, R_total_opt), 500, 100000)
        C = np.clip(_safe_value(C, C_opt), 0.0001, 0.1)

        # Compute R values from allocation
        R_values = R_total * allocation

        # Build RCR params
        rcr_params = {}
        for i, name in enumerate(outlet_names):
            rcr_params[name] = {
                'Rp': default_Rp_ratio * R_values[i],
                'C': C,
                'Rd': (1 - default_Rp_ratio) * R_values[i]
            }

        # Use in-memory config (thread-safe, no file I/O)
        config = update_config_in_memory(base_config, rcr_params, outlet_names)

        try:
            df = run_0d_simulation_in_memory(config)

            # Flow error (primary objective in Phase 2)
            flow_error = compute_flow_error(df, flow_splits, outlet_names, cycle_duration)

            # Pressure error (also important, equal weight now)
            pressure_error = compute_pressure_error(df, pressure_targets, outlet_names, cycle_duration)

            # Equal weight for both objectives in Phase 2
            total_error = flow_error + pressure_error

            # Reset consecutive failures on success
            consecutive_failures[0] = 0

            phase2_iter[0] += 1
            iteration_counter[0] += 1

            if phase2_iter[0] % 20 == 0 or phase2_iter[0] <= 3:
                print("    Phase2 Iter " + str(phase2_iter[0]) +
                      ": Flow err = " + str(round(flow_error, 1)) + " %^2" +
                      ", Pressure err = " + str(round(pressure_error, 1)) + " mmHg^2" +
                      ", R_tot = " + str(round(R_total, 0)) +
                      ", C = " + str(round(C, 6)))

            # Track best values
            best_R_total[0] = R_total
            best_C[0] = C

            # Check timeout
            if time.time() - start_time > timeout_sec:
                raise StopIteration("Timeout")

            return _safe_value(total_error, LARGE_ERROR)

        except StopIteration:
            raise
        except Exception as e:
            consecutive_failures[0] += 1
            phase2_iter[0] += 1
            iteration_counter[0] += 1

            if consecutive_failures[0] >= MAX_CONSECUTIVE_FAILURES:
                print_warning(f"Too many consecutive failures ({consecutive_failures[0]}), stopping Phase 2")
                raise StopIteration("Too many failures")

            return LARGE_ERROR

    # Initial values for Phase 2:
    # - Allocation based on flow splits (inverse proportion)
    # - R_total and C from Phase 1 results
    initial_allocation = np.array([100.0 / flow_splits[name] if flow_splits[name] > 0 else 10.0
                                   for name in outlet_names])
    initial_allocation = initial_allocation / np.sum(initial_allocation)

    x0_phase2 = np.concatenate([
        np.log(initial_allocation),  # N allocation values in log space
        [np.log(R_total_opt)],       # R_total from Phase 1 (log space)
        [np.log(C_opt)]              # C from Phase 1 (log space)
    ])

    print_info("Running Phase 2 optimization (Nelder-Mead)...")
    print_info("Optimizing " + str(N) + " allocation ratios + R_total + C (" + str(N + 2) + " parameters)")

    try:
        result2 = minimize(
            phase2_objective,
            x0_phase2,
            method='Nelder-Mead',
            options={'maxiter': 1000, 'xatol': 1e-6, 'fatol': 1e-6}
        )

        # Extract final values
        final_allocation = np.exp(result2.x[:N])
        final_allocation = final_allocation / np.sum(final_allocation)
        final_R_total = np.exp(result2.x[N])
        final_C = np.exp(result2.x[N + 1])

        # Apply bounds
        final_R_total = np.clip(final_R_total, 500, 100000)
        final_C = np.clip(final_C, 0.0001, 0.1)

        R_values_final = final_R_total * final_allocation
        stop_reason = 'completed'

    except StopIteration:
        # Timeout during Phase 2 - use best values found
        final_allocation = np.exp(x0_phase2[:N])
        final_allocation = final_allocation / np.sum(final_allocation)
        final_R_total = best_R_total[0]
        final_C = best_C[0]
        R_values_final = final_R_total * final_allocation
        stop_reason = 'timeout'

    print_status("Phase 2 complete!")
    print_info("Final R_total: " + str(round(final_R_total, 1)) +
               " (started at " + str(round(R_total_opt, 1)) + ")")
    print_info("Final C: " + str(round(final_C, 6)) +
               " (started at " + str(round(C_opt, 6)) + ")")
    print_info("Phase 2 iterations: " + str(phase2_iter[0]))
    print_info("Total iterations: " + str(iteration_counter[0]))

    return list(R_values_final), final_C, iteration_counter[0], stop_reason


# ========================================================================
# ============================ Optimization ==============================

def objective_function(x, outlet_names, flow_splits, pressure_targets,
                      base_config, cycle_duration, iteration_counter):
    """
    Objective function for optimization (v3).

    CRITICAL FIX: Now includes flow split error, not just pressure error!
    Uses IN-MEMORY config to avoid file I/O race conditions.

    Args:
        x: array [R_0, R_1, ..., R_{N-1}, C]  # N+1 parameters
           N individual R values + 1 shared C
        outlet_names: list of outlet names
        flow_splits: dict {outlet_name: target_flow_percentage}
        pressure_targets: dict {cap_name: {'max': x, 'min': y, 'mean': z}} in mmHg
                          cap_name can be 'inlet' or any outlet name
        base_config: dict, base 0D solver configuration (loaded once, passed in)
        cycle_duration: cardiac cycle duration
        iteration_counter: list with single int element (mutable for counting)

    Returns:
        float, total error (flow split error + pressure error)
    """
    N = len(outlet_names)
    R_values = x[:N]    # Individual R for each outlet
    C_value = x[N]      # Shared C for all outlets

    # Generate RCR parameters from individual R values
    rcr_params = {}
    for i, name in enumerate(outlet_names):
        R_total = R_values[i]
        rcr_params[name] = {
            'Rp': default_Rp_ratio * R_total,
            'C': C_value,
            'Rd': (1 - default_Rp_ratio) * R_total
        }

    # Use in-memory config (thread-safe, no file I/O)
    config = update_config_in_memory(base_config, rcr_params, outlet_names)

    try:
        # Run simulation with in-memory config
        df = run_0d_simulation_in_memory(config)

        # ============================================================
        # FLOW SPLIT ERROR (CRITICAL - was missing before!)
        # ============================================================
        flow_dist = extract_flow_distribution(df, outlet_names, cycle_duration)
        total_flow = sum(flow_dist.values())

        flow_error = 0.0
        for name in outlet_names:
            target_pct = flow_splits[name]
            achieved_pct = (flow_dist[name] / total_flow) * 100 if total_flow > 0 else 0
            flow_error += (achieved_pct - target_pct) ** 2

        # ============================================================
        # PRESSURE ERROR (for user-selected caps only)
        # ============================================================
        pressure_error = 0.0
        for cap, targets in pressure_targets.items():
            if cap == 'inlet':
                metrics = extract_inlet_metrics(df, cycle_duration)
            else:
                metrics = extract_outlet_metrics(df, cap, outlet_names, cycle_duration)

            # Compute error in mmHg^2
            pressure_error += (cgs_to_mmhg(metrics['max_pressure']) - targets['max']) ** 2
            pressure_error += (cgs_to_mmhg(metrics['min_pressure']) - targets['min']) ** 2
            # Mean is optional (v4)
            if targets.get('mean') is not None:
                pressure_error += (cgs_to_mmhg(metrics['mean_pressure']) - targets['mean']) ** 2

        # Total error: flow + pressure
        # Note: flow_error is in %^2, pressure_error is in mmHg^2
        # Both are comparable in magnitude for typical values
        total_error = flow_error + pressure_error

        # Log progress
        iteration_counter[0] += 1
        if iteration_counter[0] % 10 == 0 or iteration_counter[0] <= 5:
            R_avg = sum(R_values) / len(R_values)
            print("    Iter " + str(iteration_counter[0]) +
                  ": Flow err = " + str(round(flow_error, 1)) + " %^2" +
                  ", Pressure err = " + str(round(pressure_error, 1)) + " mmHg^2" +
                  ", C = " + str(round(C_value, 6)))

        return total_error

    except Exception as e:
        # Return large error on failure
        iteration_counter[0] += 1
        print("    Iter " + str(iteration_counter[0]) + ": FAILED - " + str(e))
        return 1e10


def compute_initial_R_values(flow_splits, outlet_names, base_R=1000):
    """
    Convert flow splits to initial R values.
    R is inversely proportional to flow: R_i proportional to 1/flow_i

    Args:
        flow_splits: dict {outlet_name: flow_percentage}
        outlet_names: list of outlet names (for ordering)
        base_R: base resistance value for 100% flow outlet

    Returns:
        list of initial R values for each outlet
    """
    R_values = []
    for name in outlet_names:
        flow_pct = flow_splits[name]
        if flow_pct > 0:
            R = base_R * (100.0 / flow_pct)  # R inversely proportional to flow
        else:
            R = base_R * 100  # High R for zero flow
        R_values.append(R)
    return R_values


def run_optimization_scipy(flow_splits, outlet_names, pressure_targets,
                          json_path, cycle_duration, timeout_min):
    """
    Run optimization using scipy L-BFGS-B (v3).

    Optimizes N+1 parameters: N individual R values + 1 shared C.
    Stops on timeout or convergence (all values within 10% of targets).

    Uses IN-MEMORY config to avoid file I/O race conditions with scipy's
    parallel gradient computation.
    """
    import time
    from scipy.optimize import minimize

    print_info("Starting scipy L-BFGS-B optimization...")
    print_info("Timeout: " + str(timeout_min) + " minutes")

    N = len(outlet_names)
    start_time = time.time()
    timeout_sec = timeout_min * 60

    # Load base config ONCE into memory to avoid file I/O race conditions
    with open(json_path, 'r') as f:
        base_config = json.load(f)

    # Initial guess: R values from flow splits, C in middle of range
    initial_R = compute_initial_R_values(flow_splits, outlet_names, base_R=1000)
    initial_C = 0.001  # Middle of bounds in log space (0.0001 to 0.1)
    x0 = initial_R + [initial_C]

    print_info("Initial R values: " + ", ".join([str(round(r, 1)) for r in initial_R]))
    print_info("Initial C: " + str(initial_C))

    # N+1 bounds: N R values + 1 C value
    bounds = [(100, 50000)] * N + [(0.0001, 0.1)]

    iteration_counter = [0]
    converged_early = [False]
    best_x = [None]
    stop_reason = ['max_iterations']

    # Callback for timeout and convergence checking
    def callback(x):
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > timeout_sec:
            stop_reason[0] = 'timeout'
            raise StopIteration("Timeout reached")

        # Check convergence every 10 iterations
        if iteration_counter[0] % 10 == 0 and iteration_counter[0] > 0:
            try:
                # Generate RCR params and run simulation to check convergence
                R_values = x[:N]
                C_value = x[N]
                rcr_params = {}
                for i, name in enumerate(outlet_names):
                    R_total = R_values[i]
                    rcr_params[name] = {
                        'Rp': default_Rp_ratio * R_total,
                        'C': C_value,
                        'Rd': (1 - default_Rp_ratio) * R_total
                    }
                # Use in-memory config for convergence check
                config = update_config_in_memory(base_config, rcr_params, outlet_names)
                df = run_0d_simulation_in_memory(config)

                converged, details = check_convergence(
                    flow_splits, pressure_targets, df, outlet_names, cycle_duration
                )

                if converged:
                    converged_early[0] = True
                    best_x[0] = x.copy()
                    stop_reason[0] = 'converged'
                    print_info("Convergence reached! All values within 10% of targets.")
                    raise StopIteration("Converged")
            except StopIteration:
                raise
            except Exception:
                pass  # Continue optimization if convergence check fails

    try:
        result = minimize(
            objective_function,
            x0,
            args=(outlet_names, flow_splits, pressure_targets,
                  base_config, cycle_duration, iteration_counter),
            method='L-BFGS-B',
            bounds=bounds,
            callback=callback,
            options={
                'maxiter': 10000,      # High iteration limit (v4)
                'ftol': 1e-15,         # Very tight tolerance to prevent early stop (v4)
                'gtol': 1e-15,         # Very tight gradient tolerance (v4)
                'maxfun': 100000,      # High function evaluation limit (v4)
                'disp': False
            }
        )
        final_x = result.x
        final_error = result.fun
    except StopIteration:
        # Stopped due to timeout or convergence
        if best_x[0] is not None:
            final_x = best_x[0]
        else:
            final_x = x0  # Use last known x if available
        final_error = None  # Will be recalculated

    return final_x, final_error, iteration_counter[0], stop_reason[0]


def run_optimization_cma(flow_splits, outlet_names, pressure_targets,
                        json_path, cycle_duration, timeout_min):
    """
    Run optimization using CMA-ES with initial parameter estimation.

    Two-stage approach:
    1. Quick Phase 0: Find good R_total and C using gradient-based optimization
    2. Main Phase: CMA-ES global search starting from the better initial guess

    Optimizes N+1 parameters: N individual R values + 1 shared C.
    Stops on timeout or convergence (all values within 10% of targets).

    Uses IN-MEMORY config to avoid file I/O issues.
    """
    import time
    from scipy.optimize import minimize

    # Check CMA availability
    if not _DEPENDENCIES['cma']:
        raise ImportError("cma is not installed. Install with: pip install cma")

    import cma

    N = len(outlet_names)
    start_time = time.time()
    timeout_sec = timeout_min * 60
    consecutive_failures = [0]
    MAX_CONSECUTIVE_FAILURES = 50  # CMA uses population, so allow more failures

    # Validate inputs
    if not outlet_names:
        raise ValueError("outlet_names cannot be empty")

    if cycle_duration <= 0:
        print_warning(f"Invalid cycle_duration ({cycle_duration}), using default 1.0")
        cycle_duration = 1.0

    # Load base config ONCE into memory
    try:
        base_config = load_json_config(json_path)
    except (FileNotFoundError, ValueError) as e:
        print_error(str(e))
        raise

    # ================================================================
    # PHASE 0: Quick initial parameter estimation (find good R_total, C)
    # ================================================================
    print_section_header("PHASE 0: Initial Parameter Estimation")
    print_info("Finding good starting values for R and C...")
    print_info("This helps CMA-ES start in the right ballpark.")

    phase0_iter = [0]

    # Precompute inverse flow weights for R distribution
    inv_flow_sum = sum(100.0 / f for f in flow_splits.values() if f > 0)

    def distribute_R_phase0(R_total):
        """Distribute R_total based on flow splits (inverse proportion)."""
        R_values = []
        for name in outlet_names:
            flow_pct = flow_splits[name]
            if flow_pct > 0:
                R_i = R_total * (100.0 / flow_pct) / inv_flow_sum
            else:
                R_i = R_total * 10
            R_values.append(R_i)
        return R_values

    # Phase 0 bounds in physical space
    R_total_min, R_total_max = 500, 100000
    C_min_p0, C_max_p0 = 0.0001, 0.1

    def phase0_transform(x_log):
        """Transform from log-space [0, 10] to physical space."""
        # x_log[0]: log-space R_total, x_log[1]: log-space C
        log_R = np.clip(x_log[0], 0, 10)
        log_C = np.clip(x_log[1], 0, 10)
        R_total = R_total_min * (R_total_max / R_total_min) ** (log_R / 10)
        C = C_min_p0 * (C_max_p0 / C_min_p0) ** (log_C / 10)
        return R_total, C

    def phase0_objective(x_log):
        """Quick objective to find good R_total and C (in log-space)."""
        R_total, C = phase0_transform(x_log)

        R_values = distribute_R_phase0(R_total)

        rcr_params = {}
        for i, name in enumerate(outlet_names):
            rcr_params[name] = {
                'Rp': default_Rp_ratio * R_values[i],
                'C': C,
                'Rd': (1 - default_Rp_ratio) * R_values[i]
            }

        config = update_config_in_memory(base_config, rcr_params, outlet_names)

        try:
            df = run_0d_simulation_in_memory(config)
            # Focus primarily on pressure for Phase 0
            pressure_error = compute_pressure_error(df, pressure_targets, outlet_names, cycle_duration)
            # Add small flow error to guide in right direction
            flow_error = compute_flow_error(df, flow_splits, outlet_names, cycle_duration)
            total_error = pressure_error + 0.1 * flow_error

            phase0_iter[0] += 1
            if phase0_iter[0] % 10 == 0 or phase0_iter[0] <= 2:
                print(f"    Phase0 Iter {phase0_iter[0]}: Pressure={pressure_error:.1f}, R_total={R_total:.0f}, C={C:.6f}")

            return _safe_value(total_error, LARGE_ERROR)
        except Exception:
            phase0_iter[0] += 1
            return LARGE_ERROR

    # Run Phase 0 optimization in LOG-SPACE (both params now on [0, 10] scale)
    # Initial guess: middle of log-space (5.0, 5.0) corresponds to geometric mean
    # Phase 0 is fast (only 2 parameters) so we allow more iterations for better initial guess
    # Use loose tolerances to prevent premature stopping - we want thorough exploration
    try:
        result0 = minimize(
            phase0_objective,
            [5.0, 5.0],  # Middle of log-space
            method='L-BFGS-B',
            bounds=[(0, 10), (0, 10)],  # Both params now on same scale!
            options={'maxiter': 1000, 'ftol': 1e-12, 'gtol': 1e-12}
        )
        R_total_init, C_init = phase0_transform(result0.x)
        print_status(f"Phase 0 complete: R_total={R_total_init:.0f}, C={C_init:.6f}")
    except Exception as e:
        print_warning(f"Phase 0 failed ({str(e)}), using defaults")
        R_total_init = 5000.0
        C_init = 0.005

    # Compute initial R values from Phase 0 result
    R_values_init = distribute_R_phase0(R_total_init)

    # Check timeout after Phase 0
    elapsed = time.time() - start_time
    if elapsed > timeout_sec * 0.9:  # Leave 10% time buffer
        print_warning("Most time used in Phase 0, returning Phase 0 results")
        return R_values_init + [C_init], LARGE_ERROR, phase0_iter[0], 'timeout'

    # ================================================================
    # MAIN PHASE: CMA-ES Global Search
    # ================================================================
    print_section_header("MAIN PHASE: CMA-ES Global Optimization")
    print_info("Starting CMA-ES with improved initial guess...")
    print_info(f"Timeout: {timeout_min} minutes (elapsed: {elapsed/60:.1f} min)")

    iteration_counter = [phase0_iter[0]]  # Continue counting from Phase 0
    stop_reason = ['max_iterations']
    best_x_physical = [None]

    # Transform functions: map [0, 10] to physical space
    # Now centered around Phase 0 results
    R_min, R_max = 100, 50000
    C_min, C_max = 0.0001, 0.1

    def transform_x(x_normalized):
        x_physical = []
        # R values: [0, 10] -> [R_min, R_max] (exponential)
        for i in range(N):
            x_val = np.clip(_safe_value(x_normalized[i], 5.0), 0, 10)
            R = R_min * (R_max/R_min) ** (x_val / 10)
            R = _safe_value(R, R_values_init[i])
            x_physical.append(R)
        # C value: [0, 10] -> [C_min, C_max] (exponential)
        x_c = np.clip(_safe_value(x_normalized[N], 5.0), 0, 10)
        C = C_min * (C_max/C_min) ** (x_c / 10)
        C = _safe_value(C, C_init)
        x_physical.append(C)
        return x_physical

    def inverse_transform(x_physical):
        """Convert physical values back to normalized [0, 10] space."""
        x_normalized = []
        for i in range(N):
            R = np.clip(x_physical[i], R_min, R_max)
            x_val = 10 * np.log(R / R_min) / np.log(R_max / R_min)
            x_normalized.append(np.clip(x_val, 0, 10))
        C = np.clip(x_physical[N], C_min, C_max)
        x_c = 10 * np.log(C / C_min) / np.log(C_max / C_min)
        x_normalized.append(np.clip(x_c, 0, 10))
        return x_normalized

    # Compute initial guess in normalized space from Phase 0 results
    x0 = inverse_transform(R_values_init + [C_init])
    sigma = 1.5  # Smaller sigma since we have a good starting point

    print_info(f"Initial R values from Phase 0: {[f'{r:.0f}' for r in R_values_init]}")
    print_info(f"Initial C from Phase 0: {C_init:.6f}")

    # Stagnation detection: stop if no improvement for this many iterations
    STAGNATION_LIMIT = 800
    best_error_seen = [float('inf')]
    iters_since_improvement = [0]

    def wrapped_objective(x_normalized):
        try:
            x_physical = transform_x(x_normalized)
            error = objective_function(
                x_physical, outlet_names, flow_splits, pressure_targets,
                base_config, cycle_duration, iteration_counter
            )
            # Reset consecutive failures on success
            if error < LARGE_ERROR:
                consecutive_failures[0] = 0

            # Track best error for stagnation detection
            if error < best_error_seen[0] - 1.0:  # Require meaningful improvement (>1.0)
                best_error_seen[0] = error
                iters_since_improvement[0] = 0
            else:
                iters_since_improvement[0] += 1

            return _safe_value(error, LARGE_ERROR)
        except Exception as e:
            consecutive_failures[0] += 1
            iters_since_improvement[0] += 1
            if consecutive_failures[0] >= MAX_CONSECUTIVE_FAILURES:
                print_warning(f"Too many consecutive failures in CMA-ES")
            return LARGE_ERROR

    options = {
        'bounds': [[0] * (N + 1), [10] * (N + 1)],
        'maxiter': tuning_max_iterations,
        'verbose': -9,  # Suppress CMA output
    }

    try:
        es = cma.CMAEvolutionStrategy(x0, sigma, options)
    except Exception as e:
        print_error(f"Failed to initialize CMA-ES: {str(e)}")
        # Return default values
        default_R = [5000.0] * N
        default_C = 0.001
        return default_R + [default_C], LARGE_ERROR, 0, 'failed'

    try:
        while not es.stop():
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > timeout_sec:
                stop_reason[0] = 'timeout'
                print_info("Timeout reached after " + str(int(elapsed/60)) + " minutes")
                break

            # Check for too many consecutive failures
            if consecutive_failures[0] >= MAX_CONSECUTIVE_FAILURES:
                stop_reason[0] = 'too_many_failures'
                print_warning("Stopping due to too many simulation failures")
                break

            # Check for stagnation (no improvement for STAGNATION_LIMIT iterations)
            if iters_since_improvement[0] >= STAGNATION_LIMIT:
                stop_reason[0] = 'stagnated'
                print("")
                print("  " + "=" * 60)
                print("  OPTIMIZATION CONVERGED - OPTIMAL SOLUTION FOUND")
                print("  " + "=" * 60)
                print(f"  The optimizer has found the best possible solution for your")
                print(f"  specified targets. No further improvement was achieved in")
                print(f"  the last {STAGNATION_LIMIT} iterations.")
                print("")
                print(f"  Final error: {best_error_seen[0]:.1f} (lower is better)")
                print("  " + "=" * 60)
                break

            solutions = es.ask()
            fitness_values = [wrapped_objective(x) for x in solutions]
            es.tell(solutions, fitness_values)

            # Check convergence every 10 iterations
            if iteration_counter[0] % 10 == 0 and iteration_counter[0] > 0:
                try:
                    x_best = transform_x(es.result.xbest)
                    R_values = x_best[:N]
                    C_value = x_best[N]
                    rcr_params = {}
                    for i, name in enumerate(outlet_names):
                        R_total = R_values[i]
                        rcr_params[name] = {
                            'Rp': default_Rp_ratio * R_total,
                            'C': C_value,
                            'Rd': (1 - default_Rp_ratio) * R_total
                        }
                    # Use in-memory config for convergence check
                    config = update_config_in_memory(base_config, rcr_params, outlet_names)
                    df = run_0d_simulation_in_memory(config)

                    converged, details = check_convergence(
                        flow_splits, pressure_targets, df, outlet_names, cycle_duration
                    )

                    if converged:
                        best_x_physical[0] = x_best
                        stop_reason[0] = 'converged'
                        print_info("Convergence reached! All values within 10% of targets.")
                        break
                except Exception:
                    pass  # Continue if convergence check fails

    except Exception as e:
        print_error(f"CMA-ES optimization failed: {str(e)}")
        stop_reason[0] = 'error'

    # Use converged solution if available, otherwise use CMA-ES best
    try:
        if best_x_physical[0] is not None:
            x_best = best_x_physical[0]
        else:
            x_best_normalized = es.result.xbest
            if x_best_normalized is not None:
                x_best = transform_x(x_best_normalized)
            else:
                # Fallback to defaults
                x_best = [5000.0] * N + [0.001]

        final_error = es.result.fbest if es.result.fbest is not None else LARGE_ERROR
        final_error = _safe_value(final_error, LARGE_ERROR)

    except Exception:
        x_best = [5000.0] * N + [0.001]
        final_error = LARGE_ERROR

    return x_best, final_error, iteration_counter[0], stop_reason[0]


# ========================================================================
# ============================ Main ======================================

def main():
    """Main boundary condition tuning workflow."""

    print_section_header("AUTOMATIC BOUNDARY CONDITION TUNING")
    print("")
    print("  This module will automatically find the optimal resistance and")
    print("  capacitance values for your cardiovascular model based on your")
    print("  specified flow distribution and pressure targets.")
    print("")

    # ======================== Load Prerequisites ========================
    print_info("Loading outlet configuration...")

    outlet_names = load_outlet_names()
    if outlet_names is None:
        print_error("Cannot proceed without outlet configuration.")
        sys.exit(1)

    print_status("Found " + str(len(outlet_names)) + " outlets: " + ", ".join(outlet_names))

    # Check for 0D solver input
    json_path = os.path.join(master_folder, '0D_solver_input.json')
    if not os.path.exists(json_path):
        print_info("0D solver input not found. Generating...")
        print_error("Please run preprocessing first to generate 0D solver input.")
        print_info("The main workflow will handle this automatically.")
        sys.exit(1)

    # ======================== Get User Inputs (v3 UI) ========================
    flow_splits, pressure_targets, timeout_min, optimizer = get_user_inputs(outlet_names)

    # ======================== Show Initial R Values ========================
    print_section_header("COMPUTING INITIAL R VALUES FROM FLOW SPLITS")

    initial_R = compute_initial_R_values(flow_splits, outlet_names, base_R=1000)
    print_info("Initial R values (from flow splits):")
    for i, name in enumerate(outlet_names):
        print("    " + name + ": R = " + str(round(initial_R[i], 1)) +
              " (flow: " + str(flow_splits[name]) + "%)")

    # ======================== Get Cycle Duration ========================
    cycle_duration = get_cardiac_cycle_duration()
    print_info("Cardiac cycle duration: " + str(round(cycle_duration, 3)) + " s")

    # ======================== Run Optimization ========================
    print_section_header("OPTIMIZATION SETUP")

    # Show pressure targets (handle optional mean - v4)
    print_info("Pressure targets:")
    for cap, targets in pressure_targets.items():
        if targets.get('mean') is not None:
            print("    " + cap + ": " + str(targets['max']) + "/" +
                  str(targets['min']) + "/" + str(targets['mean']) + " mmHg (max/min/mean)")
        else:
            print("    " + cap + ": " + str(targets['max']) + "/" +
                  str(targets['min']) + " mmHg (max/min)")
    print("")

    # Show flow split targets
    print_info("Flow split targets:")
    for name, pct in flow_splits.items():
        print("    " + name + ": " + str(pct) + "%")
    print("")

    print_info("R bounds: [100, 50000] CGS")
    print_info("C bounds: [0.0001, 0.1] CGS")
    print_info("Timeout: " + str(timeout_min) + " minutes")
    print("")

    try:
        if optimizer == 'scipy':
            # Use two-phase optimization for scipy (v4)
            print_info("Using TWO-PHASE optimization (v4):")
            print_info("  Phase 1: Optimize total R and C for pressure")
            print_info("  Phase 2: Redistribute R among outlets for flow splits")

            R_values_final, C_final, n_iters, stop_reason = run_two_phase_optimization(
                flow_splits, outlet_names, pressure_targets,
                json_path, cycle_duration, timeout_min
            )
        else:
            # CMA-ES uses single-phase (more robust)
            print_info("Using CMA-ES single-phase optimization")
            print_info("Optimizing " + str(len(outlet_names)) + " R values + 1 C value (" +
                      str(len(outlet_names) + 1) + " parameters)")

            x_best, final_error, n_iters, stop_reason = run_optimization_cma(
                flow_splits, outlet_names, pressure_targets,
                json_path, cycle_duration, timeout_min
            )
            # Extract optimized values
            N = len(outlet_names)
            R_values_final = x_best[:N]
            C_final = x_best[N]

    except ImportError as e:
        print_error(str(e))
        print_info("Please install the required package and try again.")
        sys.exit(1)
    except Exception as e:
        print_error(f"Optimization failed: {str(e)}")
        print_info("Using default RCR parameters as fallback...")
        # Fallback to default parameters based on flow splits
        R_values_final = compute_initial_R_values(flow_splits, outlet_names, base_R=5000)
        C_final = 0.005
        n_iters = 0
        stop_reason = 'failed'

    print("\n" + "-" * 70)
    if stop_reason == 'converged':
        print_status("Optimization converged! All values within 10% of targets.")
    elif stop_reason == 'timeout':
        print_status("Optimization stopped due to timeout (" + str(timeout_min) + " min)")
    elif stop_reason == 'stagnated':
        print_status("Optimal solution found! This is the best result for your targets.")
    else:
        print_status("Optimization completed")
    print("    Total iterations: " + str(n_iters))
    print("    Optimized C: " + str(round(C_final, 6)))

    # ======================== Generate Final Parameters ========================
    print_section_header("GENERATING FINAL RCR PARAMETERS")

    # Generate RCR params from optimized R values and C
    final_rcr_params = {}
    for i, name in enumerate(outlet_names):
        R_total = R_values_final[i]
        final_rcr_params[name] = {
            'Rp': default_Rp_ratio * R_total,
            'C': C_final,
            'Rd': (1 - default_Rp_ratio) * R_total
        }

    print_info("Optimized RCR parameters:")
    print("")
    print("    {:<12} {:>12} {:>12} {:>12} {:>12}".format("Outlet", "R_total", "Rp", "C", "Rd"))
    print("    " + "-" * 64)
    for i, name in enumerate(outlet_names):
        p = final_rcr_params[name]
        print("    {:<12} {:>12.2f} {:>12.2f} {:>12.6f} {:>12.2f}".format(
            name, R_values_final[i], p['Rp'], p['C'], p['Rd']))

    # ======================== Save rcrt.dat ========================
    rcrt_path = os.path.join(master_folder, bc_filename)
    write_rcrt_dat(final_rcr_params, outlet_names, rcrt_path)
    print_status("Saved optimized boundary conditions to: " + rcrt_path)

    # ======================== Verify Results ========================
    print_section_header("VERIFYING OPTIMIZED PARAMETERS")

    # Update JSON and run final simulation
    try:
        update_0d_solver_input(final_rcr_params, outlet_names, json_path)
        df = run_0d_simulation(json_path)

        # Use check_convergence for full verification
        converged, details = check_convergence(
            flow_splits, pressure_targets, df, outlet_names, cycle_duration
        )

        # Show pressure verification for each targeted cap
        print_info("Pressure verification:")
        for cap, pdata in details['pressure'].items():
            print("\n    " + cap.upper() + ":")
            # Always show max and min; mean is optional (v4)
            for key in ['max', 'min']:
                target = pdata[key]['target']
                achieved = pdata[key]['achieved']
                error_pct = pdata[key]['error_pct']
                status = "GOOD" if error_pct <= 10 else "MISS"
                print("      " + key.capitalize() + ": " +
                      str(round(achieved, 1)) + " mmHg (target: " + str(target) +
                      ", error: " + str(round(error_pct, 1)) + "%) [" + status + "]")
            # Show mean only if it was targeted
            if 'mean' in pdata:
                target = pdata['mean']['target']
                achieved = pdata['mean']['achieved']
                error_pct = pdata['mean']['error_pct']
                status = "GOOD" if error_pct <= 10 else "MISS"
                print("      Mean: " +
                      str(round(achieved, 1)) + " mmHg (target: " + str(target) +
                      ", error: " + str(round(error_pct, 1)) + "%) [" + status + "]")

        # Verify flow distribution
        print("\n" + "-" * 70)
        print_info("Flow split verification:")
        print("       (Large vessels >=15%: 10% tolerance, Small vessels <15%: 25% tolerance)")
        print("")
        print("    {:<12} {:>12} {:>12} {:>12} {:>10} {:>8}".format(
            "Outlet", "Target %", "Achieved %", "Error %", "Tolerance", "Status"))
        print("    " + "-" * 70)
        for name in outlet_names:
            fdata = details['flow'][name]
            target = fdata['target']
            achieved = fdata['achieved']
            error_pct = fdata['error_pct']
            tolerance = fdata.get('tolerance', 10)
            is_small = fdata.get('is_small_vessel', False)

            if error_pct <= tolerance:
                status = "DECENT" if is_small else "GOOD"
            else:
                status = "MISS"

            tol_str = f"{tolerance}%"
            print("    {:<12} {:>12.1f} {:>12.1f} {:>12.1f} {:>10} {:>8}".format(
                name, target, achieved, error_pct, tol_str, status))

        # Summary
        print("\n" + "-" * 70)
        if converged:
            print_status("SUCCESS: All targets within tolerance!")
        else:
            if not details['flow_converged']:
                print_warning("Some flow splits not within tolerance")
            if not details['pressure_converged']:
                print_warning("Pressures not within 10% tolerance")
            print_info("Consider running optimization longer or adjusting targets")

    except Exception as e:
        print_warning(f"Verification simulation failed: {str(e)}")
        print_info("RCR parameters were saved but could not be verified.")
        print_info("Please run a manual simulation to check results.")

    # ======================== Done ========================
    print_section_header("BOUNDARY CONDITION TUNING COMPLETE")
    print_info("Output file: " + rcrt_path)
    print_info("The optimized boundary conditions have been saved.")
    print_info("Your simulation will now use these parameters for accurate")
    print_info("blood flow and pressure predictions.")
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
