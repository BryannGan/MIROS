"""
Optimization Method Comparison Test

Compares different optimization methods for BC tuning:
1. scipy L-BFGS-B (single-phase)
2. Two-Phase scipy (pressure then flow)
3. CMA-ES
4. Nelder-Mead

Generates comparison plots showing error reduction over iterations.
"""

import os
import sys
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from copy import deepcopy
import time

# Add package to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from package import *

# Import pysvzerod for 0D simulation
import pysvzerod

# ========================================================================
# Test Configuration
# ========================================================================

TEST_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test_Linux_Mac'))
RESULTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'results'))

# Fixed test inputs (no user prompts)
FLOW_SPLITS = {
    'cap_2': 50.0,
    'cap_4': 10.0,
    'cap_5': 20.0,
    'cap_6': 10.0,
    'cap_7': 10.0
}

PRESSURE_TARGETS = {
    'inlet': {'max': 120.0, 'min': 80.0, 'mean': None}
}

MAX_ITERATIONS = 300  # Same for all methods

# RCR parameters
DEFAULT_RP_RATIO = 0.09
MMHG_TO_CGS = 1333.22

# ========================================================================
# Helper Functions
# ========================================================================

def cgs_to_mmhg(pressure_cgs):
    """Convert pressure from CGS (dyn/cm^2) to mmHg."""
    return pressure_cgs / MMHG_TO_CGS


def run_0d_simulation_in_memory(config):
    """Run 0D solver with in-memory config dict and return results as DataFrame."""
    solver = pysvzerod.Solver(config)
    solver.run()
    data = solver.get_full_result()
    df = pd.DataFrame(data)
    return df


def update_config_in_memory(base_config, rcr_params, outlet_names):
    """
    Update config dict with new RCR values.
    Returns a deep copy with updated values.
    """
    config = deepcopy(base_config)

    for i, bc in enumerate(config['boundary_conditions']):
        if bc['bc_type'] == 'RCR':
            rcr_idx = int(bc['bc_name'].replace('RCR_', ''))
            if rcr_idx < len(outlet_names):
                outlet_name = outlet_names[rcr_idx]
                if outlet_name in rcr_params:
                    params = rcr_params[outlet_name]
                    bc['bc_values']['Rp'] = params['Rp']
                    bc['bc_values']['C'] = params['C']
                    bc['bc_values']['Rd'] = params['Rd']

    return config


def extract_inlet_metrics(df, cycle_duration):
    """Extract pressure metrics at inlet."""
    segments = df['name'].unique().tolist()

    inlet_segment = None
    for seg in segments:
        if 'seg0' in seg or seg.endswith('_0'):
            inlet_segment = seg
            break

    if inlet_segment is None:
        inlet_segment = sorted(segments)[0]

    seg_data = df[df['name'] == inlet_segment].copy()
    seg_data = seg_data.sort_values('time')

    max_time = seg_data['time'].max()
    num_cycles = int(max_time / cycle_duration)
    start_time = (num_cycles - 1) * cycle_duration if num_cycles >= 1 else 0
    last_cycle = seg_data[seg_data['time'] >= start_time]

    return {
        'max_pressure': last_cycle['pressure_in'].max(),
        'min_pressure': last_cycle['pressure_in'].min(),
        'mean_pressure': last_cycle['pressure_in'].mean()
    }


def extract_flow_distribution(df, outlet_names, cycle_duration):
    """Extract flow distribution across outlets."""
    segments = df['name'].unique().tolist()

    branch_segments = {}
    for seg in segments:
        parts = seg.split('_')
        if len(parts) >= 2:
            branch = parts[0]
            seg_num = int(parts[1].replace('seg', ''))
            if branch not in branch_segments:
                branch_segments[branch] = []
            branch_segments[branch].append((seg_num, seg))

    outlet_segments = []
    for branch, segs in sorted(branch_segments.items()):
        segs.sort(key=lambda x: x[0])
        outlet_segments.append(segs[-1][1])

    flow_dist = {}
    max_time = df['time'].max()
    num_cycles = int(max_time / cycle_duration)
    start_time = (num_cycles - 1) * cycle_duration if num_cycles >= 1 else 0

    for i, seg in enumerate(outlet_segments):
        if i < len(outlet_names):
            seg_data = df[df['name'] == seg]
            last_cycle = seg_data[seg_data['time'] >= start_time]
            flow_dist[outlet_names[i]] = abs(last_cycle['flow_out'].mean())

    return flow_dist


def compute_flow_error(df, flow_splits, outlet_names, cycle_duration):
    """Compute flow split error (sum of squared percentage errors)."""
    flow_dist = extract_flow_distribution(df, outlet_names, cycle_duration)
    total_flow = sum(flow_dist.values())

    flow_error = 0.0
    for name in outlet_names:
        target_pct = flow_splits[name]
        achieved_pct = (flow_dist[name] / total_flow) * 100 if total_flow > 0 else 0
        flow_error += (achieved_pct - target_pct) ** 2

    return flow_error


def compute_pressure_error(df, pressure_targets, outlet_names, cycle_duration):
    """Compute pressure error (sum of squared mmHg errors)."""
    pressure_error = 0.0

    for cap, targets in pressure_targets.items():
        if cap == 'inlet':
            metrics = extract_inlet_metrics(df, cycle_duration)
        else:
            continue  # Skip non-inlet for simplicity

        pressure_error += (cgs_to_mmhg(metrics['max_pressure']) - targets['max']) ** 2
        pressure_error += (cgs_to_mmhg(metrics['min_pressure']) - targets['min']) ** 2
        if targets.get('mean') is not None:
            pressure_error += (cgs_to_mmhg(metrics['mean_pressure']) - targets['mean']) ** 2

    return pressure_error


# ========================================================================
# Optimization Methods with History Tracking
# ========================================================================

def run_scipy_lbfgsb(outlet_names, base_config, cycle_duration, max_iters):
    """
    Run scipy L-BFGS-B single-phase optimization with history tracking.
    Optimizes N R values + 1 C value.
    Uses in-memory config to avoid file I/O race conditions.
    """
    from scipy.optimize import minimize

    print("\n" + "=" * 60)
    print("  Running: scipy L-BFGS-B (single-phase)")
    print("=" * 60)

    N = len(outlet_names)
    history = []

    # Initial R values from flow splits (inverse proportion)
    def compute_initial_R():
        R_values = []
        for name in outlet_names:
            flow_pct = FLOW_SPLITS[name]
            if flow_pct > 0:
                R = 1000 * (100.0 / flow_pct)
            else:
                R = 1000 * 100
            R_values.append(R)
        return R_values

    initial_R = compute_initial_R()
    initial_C = 0.001
    x0 = initial_R + [initial_C]

    bounds = [(100, 50000)] * N + [(0.0001, 0.1)]
    iteration_counter = [0]

    def objective(x):
        R_values = x[:N]
        C_value = x[N]

        rcr_params = {}
        for i, name in enumerate(outlet_names):
            rcr_params[name] = {
                'Rp': DEFAULT_RP_RATIO * R_values[i],
                'C': C_value,
                'Rd': (1 - DEFAULT_RP_RATIO) * R_values[i]
            }

        config = update_config_in_memory(base_config, rcr_params, outlet_names)

        try:
            df = run_0d_simulation_in_memory(config)
            flow_err = compute_flow_error(df, FLOW_SPLITS, outlet_names, cycle_duration)
            pressure_err = compute_pressure_error(df, PRESSURE_TARGETS, outlet_names, cycle_duration)
            total_err = flow_err + pressure_err

            iteration_counter[0] += 1
            history.append({
                'iteration': iteration_counter[0],
                'flow_error': flow_err,
                'pressure_error': pressure_err,
                'total_error': total_err
            })

            if iteration_counter[0] % 20 == 0:
                print(f"    Iter {iteration_counter[0]}: Flow={flow_err:.1f}, Pressure={pressure_err:.1f}")

            return total_err
        except Exception as e:
            iteration_counter[0] += 1
            return 1e10

    result = minimize(
        objective,
        x0,
        method='L-BFGS-B',
        bounds=bounds,
        options={'maxiter': max_iters, 'ftol': 1e-12, 'gtol': 1e-12}
    )

    print(f"  Completed: {iteration_counter[0]} iterations")
    return pd.DataFrame(history)


def run_two_phase(outlet_names, base_config, cycle_duration, max_iters):
    """
    Run two-phase optimization with history tracking.
    Phase 1: Optimize total R and C for pressure
    Phase 2: Redistribute R for flow splits
    """
    from scipy.optimize import minimize

    print("\n" + "=" * 60)
    print("  Running: Two-Phase scipy")
    print("=" * 60)

    N = len(outlet_names)
    history = []
    iteration_counter = [0]

    # Precompute inverse flow weights
    inv_flow_sum = sum(100.0 / f for f in FLOW_SPLITS.values() if f > 0)

    def distribute_R(R_total):
        R_values = []
        for name in outlet_names:
            flow_pct = FLOW_SPLITS[name]
            if flow_pct > 0:
                R_i = R_total * (100.0 / flow_pct) / inv_flow_sum
            else:
                R_i = R_total * 10
            R_values.append(R_i)
        return R_values

    # Phase 1: Optimize R_total and C for pressure
    print("  Phase 1: Pressure optimization...")

    def phase1_objective(x):
        R_total, C = x[0], x[1]
        R_values = distribute_R(R_total)

        rcr_params = {}
        for i, name in enumerate(outlet_names):
            rcr_params[name] = {
                'Rp': DEFAULT_RP_RATIO * R_values[i],
                'C': C,
                'Rd': (1 - DEFAULT_RP_RATIO) * R_values[i]
            }

        config = update_config_in_memory(base_config, rcr_params, outlet_names)

        try:
            df = run_0d_simulation_in_memory(config)
            flow_err = compute_flow_error(df, FLOW_SPLITS, outlet_names, cycle_duration)
            pressure_err = compute_pressure_error(df, PRESSURE_TARGETS, outlet_names, cycle_duration)
            total_err = flow_err + pressure_err

            iteration_counter[0] += 1
            history.append({
                'iteration': iteration_counter[0],
                'flow_error': flow_err,
                'pressure_error': pressure_err,
                'total_error': total_err,
                'phase': 1
            })

            if iteration_counter[0] % 20 == 0:
                print(f"    Phase1 Iter {iteration_counter[0]}: Pressure={pressure_err:.1f}")

            return pressure_err  # Phase 1 optimizes pressure only
        except:
            iteration_counter[0] += 1
            return 1e10

    x0_phase1 = [5000.0, 0.005]
    bounds_phase1 = [(500, 100000), (0.0001, 0.1)]

    result1 = minimize(
        phase1_objective,
        x0_phase1,
        method='L-BFGS-B',
        bounds=bounds_phase1,
        options={'maxiter': max_iters // 2, 'ftol': 1e-10, 'gtol': 1e-10}
    )

    R_total_opt = result1.x[0]
    C_opt = result1.x[1]
    print(f"  Phase 1 complete: R_total={R_total_opt:.0f}, C={C_opt:.6f}")

    # Phase 2: Optimize flow splits AND fine-tune R_total/C
    print("  Phase 2: Flow split + R_total/C fine-tuning...")
    phase2_iter = [0]

    def phase2_objective(params):
        # Extract parameters: N allocation values + R_total + C (all in log space)
        allocation_raw = params[:N]
        log_R_total = params[N]
        log_C = params[N + 1]

        # Convert from log space
        allocation = np.exp(allocation_raw)
        allocation = allocation / np.sum(allocation)
        R_total = np.exp(log_R_total)
        C = np.exp(log_C)

        # Enforce bounds
        R_total = np.clip(R_total, 500, 100000)
        C = np.clip(C, 0.0001, 0.1)

        R_values = R_total * allocation

        rcr_params = {}
        for i, name in enumerate(outlet_names):
            rcr_params[name] = {
                'Rp': DEFAULT_RP_RATIO * R_values[i],
                'C': C,
                'Rd': (1 - DEFAULT_RP_RATIO) * R_values[i]
            }

        config = update_config_in_memory(base_config, rcr_params, outlet_names)

        try:
            df = run_0d_simulation_in_memory(config)
            flow_err = compute_flow_error(df, FLOW_SPLITS, outlet_names, cycle_duration)
            pressure_err = compute_pressure_error(df, PRESSURE_TARGETS, outlet_names, cycle_duration)
            total_err = flow_err + pressure_err  # Equal weight in Phase 2

            iteration_counter[0] += 1
            phase2_iter[0] += 1
            history.append({
                'iteration': iteration_counter[0],
                'flow_error': flow_err,
                'pressure_error': pressure_err,
                'total_error': total_err,
                'phase': 2
            })

            if phase2_iter[0] % 20 == 0:
                print(f"    Phase2 Iter {phase2_iter[0]}: Flow={flow_err:.1f}, Pressure={pressure_err:.1f}")

            return total_err
        except:
            iteration_counter[0] += 1
            phase2_iter[0] += 1
            return 1e10

    # Initial values: allocation from flow splits, R_total and C from Phase 1
    initial_allocation = np.array([100.0 / FLOW_SPLITS[name] if FLOW_SPLITS[name] > 0 else 10.0
                                   for name in outlet_names])
    initial_allocation = initial_allocation / np.sum(initial_allocation)

    x0_phase2 = np.concatenate([
        np.log(initial_allocation),  # N allocation values
        [np.log(R_total_opt)],       # R_total from Phase 1
        [np.log(C_opt)]              # C from Phase 1
    ])

    result2 = minimize(
        phase2_objective,
        x0_phase2,
        method='Nelder-Mead',
        options={'maxiter': max_iters // 2, 'xatol': 1e-6, 'fatol': 1e-6}
    )

    # Extract final values for logging
    final_R_total = np.exp(result2.x[N])
    final_C = np.exp(result2.x[N + 1])
    print(f"  Phase 2 complete: R_total={final_R_total:.0f} (was {R_total_opt:.0f}), C={final_C:.6f} (was {C_opt:.6f})")
    print(f"  Completed: {iteration_counter[0]} total iterations")
    return pd.DataFrame(history)


def run_cma_es(outlet_names, base_config, cycle_duration, max_iters):
    """
    Run CMA-ES optimization with history tracking.
    """
    try:
        import cma
    except ImportError:
        print("  CMA-ES not available (install with: pip install cma)")
        return pd.DataFrame()

    print("\n" + "=" * 60)
    print("  Running: CMA-ES")
    print("=" * 60)

    N = len(outlet_names)
    history = []
    iteration_counter = [0]

    x0 = [5.0] * (N + 1)
    sigma = 2.0

    def transform_x(x_normalized):
        x_physical = []
        for i in range(N):
            R = 100 * (50000/100) ** (x_normalized[i] / 10)
            x_physical.append(R)
        C = 0.0001 * (0.1/0.0001) ** (x_normalized[N] / 10)
        x_physical.append(C)
        return x_physical

    def objective(x_normalized):
        x_physical = transform_x(x_normalized)
        R_values = x_physical[:N]
        C_value = x_physical[N]

        rcr_params = {}
        for i, name in enumerate(outlet_names):
            rcr_params[name] = {
                'Rp': DEFAULT_RP_RATIO * R_values[i],
                'C': C_value,
                'Rd': (1 - DEFAULT_RP_RATIO) * R_values[i]
            }

        config = update_config_in_memory(base_config, rcr_params, outlet_names)

        try:
            df = run_0d_simulation_in_memory(config)
            flow_err = compute_flow_error(df, FLOW_SPLITS, outlet_names, cycle_duration)
            pressure_err = compute_pressure_error(df, PRESSURE_TARGETS, outlet_names, cycle_duration)
            total_err = flow_err + pressure_err

            iteration_counter[0] += 1
            history.append({
                'iteration': iteration_counter[0],
                'flow_error': flow_err,
                'pressure_error': pressure_err,
                'total_error': total_err
            })

            if iteration_counter[0] % 50 == 0:
                print(f"    Iter {iteration_counter[0]}: Flow={flow_err:.1f}, Pressure={pressure_err:.1f}")

            return total_err
        except:
            iteration_counter[0] += 1
            return 1e10

    options = {
        'bounds': [[0] * (N + 1), [10] * (N + 1)],
        'maxfevals': max_iters * 10,  # CMA uses function evals, not iterations
        'verbose': -9
    }

    es = cma.CMAEvolutionStrategy(x0, sigma, options)

    while not es.stop() and iteration_counter[0] < max_iters * 10:
        solutions = es.ask()
        es.tell(solutions, [objective(x) for x in solutions])

    print(f"  Completed: {iteration_counter[0]} iterations")
    return pd.DataFrame(history)


def run_nelder_mead(outlet_names, base_config, cycle_duration, max_iters):
    """
    Run Nelder-Mead optimization with history tracking.
    """
    from scipy.optimize import minimize

    print("\n" + "=" * 60)
    print("  Running: Nelder-Mead")
    print("=" * 60)

    N = len(outlet_names)
    history = []
    iteration_counter = [0]

    # Initial R values from flow splits
    def compute_initial_R():
        R_values = []
        for name in outlet_names:
            flow_pct = FLOW_SPLITS[name]
            if flow_pct > 0:
                R = 1000 * (100.0 / flow_pct)
            else:
                R = 1000 * 100
            R_values.append(R)
        return R_values

    initial_R = compute_initial_R()
    initial_C = 0.001

    # Normalize to [0, 10] for Nelder-Mead
    def to_normalized(R_values, C):
        x = []
        for R in R_values:
            x.append(10 * np.log(R / 100) / np.log(50000 / 100))
        x.append(10 * np.log(C / 0.0001) / np.log(0.1 / 0.0001))
        return np.array(x)

    def from_normalized(x):
        R_values = []
        for i in range(N):
            R = 100 * (50000/100) ** (x[i] / 10)
            R_values.append(R)
        C = 0.0001 * (0.1/0.0001) ** (x[N] / 10)
        return R_values, C

    x0 = to_normalized(initial_R, initial_C)

    def objective(x_normalized):
        R_values, C_value = from_normalized(x_normalized)

        rcr_params = {}
        for i, name in enumerate(outlet_names):
            rcr_params[name] = {
                'Rp': DEFAULT_RP_RATIO * R_values[i],
                'C': C_value,
                'Rd': (1 - DEFAULT_RP_RATIO) * R_values[i]
            }

        config = update_config_in_memory(base_config, rcr_params, outlet_names)

        try:
            df = run_0d_simulation_in_memory(config)
            flow_err = compute_flow_error(df, FLOW_SPLITS, outlet_names, cycle_duration)
            pressure_err = compute_pressure_error(df, PRESSURE_TARGETS, outlet_names, cycle_duration)
            total_err = flow_err + pressure_err

            iteration_counter[0] += 1
            history.append({
                'iteration': iteration_counter[0],
                'flow_error': flow_err,
                'pressure_error': pressure_err,
                'total_error': total_err
            })

            if iteration_counter[0] % 20 == 0:
                print(f"    Iter {iteration_counter[0]}: Flow={flow_err:.1f}, Pressure={pressure_err:.1f}")

            return total_err
        except:
            iteration_counter[0] += 1
            return 1e10

    result = minimize(
        objective,
        x0,
        method='Nelder-Mead',
        options={'maxiter': max_iters, 'xatol': 1e-6, 'fatol': 1e-6}
    )

    print(f"  Completed: {iteration_counter[0]} iterations")
    return pd.DataFrame(history)


# ========================================================================
# Main Comparison Function
# ========================================================================

def run_comparison():
    """Run all optimization methods and generate comparison plots."""

    print("\n" + "=" * 70)
    print("  OPTIMIZATION METHOD COMPARISON TEST")
    print("=" * 70)

    # Create results directory
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

    # Load test data
    json_path = os.path.join(TEST_DATA_DIR, '0D_solver_input.json')
    outlets_file = os.path.join(TEST_DATA_DIR, 'centerlines_outlets.dat')

    if not os.path.exists(json_path):
        print(f"  [ERROR] 0D solver input not found: {json_path}")
        return

    with open(outlets_file, 'r') as f:
        outlet_names = [line.strip() for line in f.readlines() if line.strip()]

    print(f"\n  Test data: {TEST_DATA_DIR}")
    print(f"  Outlets: {', '.join(outlet_names)}")
    print(f"  Max iterations per method: {MAX_ITERATIONS}")

    # Get cycle duration
    inflow_path = os.path.join(TEST_DATA_DIR, 'inflow_1d.flow')
    inflow_data = np.loadtxt(inflow_path)
    cycle_duration = inflow_data[-1, 0]
    print(f"  Cycle duration: {cycle_duration:.3f} s")

    # Show targets
    print(f"\n  Flow split targets: {FLOW_SPLITS}")
    print(f"  Pressure targets: {PRESSURE_TARGETS}")

    # Load original config ONCE into memory
    with open(json_path, 'r') as f:
        base_config = json.load(f)

    results = {}

    # Run each method
    methods = [
        ('scipy_lbfgsb', run_scipy_lbfgsb),
        ('two_phase', run_two_phase),
        ('cma_es', run_cma_es),
        ('nelder_mead', run_nelder_mead)
    ]

    for method_name, method_func in methods:
        try:
            history_df = method_func(outlet_names, base_config, cycle_duration, MAX_ITERATIONS)

            if not history_df.empty:
                results[method_name] = history_df
                history_df.to_csv(os.path.join(RESULTS_DIR, f'{method_name}_history.csv'), index=False)
                print(f"  Saved: {method_name}_history.csv")
        except Exception as e:
            print(f"  [ERROR] {method_name} failed: {e}")
            import traceback
            traceback.print_exc()

    # Generate comparison plot
    if results:
        plot_comparison(results)
    else:
        print("\n  [ERROR] No results to plot")


def plot_comparison(results):
    """Generate comparison plots."""

    print("\n" + "-" * 70)
    print("  Generating comparison plots...")
    print("-" * 70)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    colors = {
        'scipy_lbfgsb': 'blue',
        'two_phase': 'green',
        'cma_es': 'red',
        'nelder_mead': 'orange'
    }

    labels = {
        'scipy_lbfgsb': 'scipy L-BFGS-B',
        'two_phase': 'Two-Phase',
        'cma_es': 'CMA-ES',
        'nelder_mead': 'Nelder-Mead'
    }

    # Plot 1: Total Error
    ax = axes[0]
    for method, history in results.items():
        ax.plot(history['iteration'], history['total_error'],
                label=labels.get(method, method), color=colors.get(method, 'black'),
                linewidth=1.5)
    ax.set_xlabel('Iteration')
    ax.set_ylabel('Total Error')
    ax.set_title('Total Error vs Iteration')
    ax.legend()
    ax.set_yscale('log')
    ax.grid(True, alpha=0.3)

    # Plot 2: Flow Error
    ax = axes[1]
    for method, history in results.items():
        ax.plot(history['iteration'], history['flow_error'],
                label=labels.get(method, method), color=colors.get(method, 'black'),
                linewidth=1.5)
    ax.set_xlabel('Iteration')
    ax.set_ylabel('Flow Error (%^2)')
    ax.set_title('Flow Split Error')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Plot 3: Pressure Error
    ax = axes[2]
    for method, history in results.items():
        ax.plot(history['iteration'], history['pressure_error'],
                label=labels.get(method, method), color=colors.get(method, 'black'),
                linewidth=1.5)
    ax.set_xlabel('Iteration')
    ax.set_ylabel('Pressure Error (mmHg^2)')
    ax.set_title('Pressure Error')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    plot_path = os.path.join(RESULTS_DIR, 'comparison_plot.png')
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    print(f"\n  Plot saved to: {plot_path}")

    # Also save as PDF for high quality
    pdf_path = os.path.join(RESULTS_DIR, 'comparison_plot.pdf')
    plt.savefig(pdf_path, bbox_inches='tight')
    print(f"  PDF saved to: {pdf_path}")

    plt.close()

    # Print summary statistics
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    print(f"\n  {'Method':<20} {'Final Flow Err':<15} {'Final Pres Err':<15} {'Iterations':<12}")
    print("  " + "-" * 62)

    for method, history in results.items():
        final_flow = history['flow_error'].iloc[-1]
        final_pres = history['pressure_error'].iloc[-1]
        n_iters = len(history)
        print(f"  {labels.get(method, method):<20} {final_flow:<15.1f} {final_pres:<15.1f} {n_iters:<12}")


if __name__ == '__main__':
    run_comparison()
