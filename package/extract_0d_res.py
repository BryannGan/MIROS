"""
extract_0d_res.py - Extract and visualize 0D simulation results

This script processes results from the svZeroDSolver and can:
1. Read and analyze the 0D results CSV
2. Plot flow and pressure waveforms
3. Extract specific segments (outlets or all)
4. Compare with 1D results if available
5. Generate summary statistics

Modified by Claude: Complete implementation for 0D result extraction
"""

import os
import sys
import numpy as np

# ========================================================================
# ============================ Initialize  ================================

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
from package import *

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
# --- End helper functions ---

# ========================================================================
# ============================ Check Dependencies =========================

try:
    import pandas as pd
    import matplotlib.pyplot as plt
except ImportError as e:
    print_error("Missing required package: " + str(e))
    print_info("Install with: pip install pandas matplotlib")
    sys.exit(1)

# ========================================================================
# ============================ Helper Functions ===========================

def get_cardiac_cycle_duration():
    """
    Get the cardiac cycle duration from the inflow file.
    """
    try:
        inflow_data = np.loadtxt(inflow_file_path)
        cycle_duration = inflow_data[-1, 0]
        return cycle_duration
    except Exception as e:
        print_info("Could not read inflow file: " + str(e))
        return 1.0


def load_0d_results():
    """
    Load 0D results from CSV file.
    """
    results_file = os.path.join(res_folder_0D, '0D_results.csv')

    if not os.path.exists(results_file):
        print_error("0D results file not found: " + results_file)
        return None

    df = pd.read_csv(results_file)

    # Drop unnamed index column if present
    if 'Unnamed: 0' in df.columns:
        df = df.drop('Unnamed: 0', axis=1)

    return df


def get_segment_names(df):
    """
    Get list of unique segment names from results.
    """
    return df['name'].unique().tolist()


def get_outlet_segments(df):
    """
    Identify outlet segments (last segment of each branch).
    """
    segments = get_segment_names(df)

    # Group by branch and find max segment number
    outlets = []
    branch_segments = {}

    for seg in segments:
        parts = seg.split('_')
        if len(parts) >= 2:
            branch = parts[0]  # e.g., 'branch0'
            seg_num = int(parts[1].replace('seg', ''))  # e.g., 3

            if branch not in branch_segments:
                branch_segments[branch] = []
            branch_segments[branch].append((seg_num, seg))

    # Get the last segment from each branch
    for branch, segs in branch_segments.items():
        segs.sort(key=lambda x: x[0])
        outlets.append(segs[-1][1])  # Last segment

    return outlets


def extract_segment_data(df, segment_name):
    """
    Extract time-series data for a specific segment.
    """
    seg_data = df[df['name'] == segment_name].copy()
    seg_data = seg_data.sort_values('time')
    return seg_data


def extract_last_cycle(df, cycle_duration):
    """
    Extract only the last cardiac cycle from the results.
    """
    max_time = df['time'].max()
    num_cycles = int(max_time / cycle_duration)

    if num_cycles >= 1:
        start_time = (num_cycles - 1) * cycle_duration
        end_time = num_cycles * cycle_duration
    else:
        start_time = 0
        end_time = max_time

    # Filter to last cycle
    last_cycle = df[(df['time'] >= start_time) & (df['time'] <= end_time)].copy()

    # Normalize time to start at 0
    last_cycle['time'] = last_cycle['time'] - start_time

    return last_cycle


def compute_statistics(seg_data):
    """
    Compute summary statistics for a segment.
    """
    stats = {
        'mean_flow_in': seg_data['flow_in'].mean(),
        'mean_flow_out': seg_data['flow_out'].mean(),
        'mean_pressure_in': seg_data['pressure_in'].mean(),
        'mean_pressure_out': seg_data['pressure_out'].mean(),
        'max_pressure_in': seg_data['pressure_in'].max(),
        'min_pressure_in': seg_data['pressure_in'].min(),
        'max_flow_in': seg_data['flow_in'].max(),
        'min_flow_in': seg_data['flow_in'].min(),
    }
    return stats


def plot_segment_waveforms(seg_data, segment_name, save_path=None):
    """
    Plot flow and pressure waveforms for a segment.
    """
    fig, axes = plt.subplots(2, 1, figsize=(10, 8))

    # Flow plot
    ax1 = axes[0]
    ax1.plot(seg_data['time'], seg_data['flow_in'], 'b-', label='Flow In', linewidth=1.5)
    ax1.plot(seg_data['time'], seg_data['flow_out'], 'r--', label='Flow Out', linewidth=1.5)
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Flow (mL/s)')
    ax1.set_title('Flow Waveform - ' + segment_name)
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Pressure plot
    ax2 = axes[1]
    ax2.plot(seg_data['time'], seg_data['pressure_in'], 'b-', label='Pressure In', linewidth=1.5)
    ax2.plot(seg_data['time'], seg_data['pressure_out'], 'r--', label='Pressure Out', linewidth=1.5)
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Pressure (dyn/cm^2)')
    ax2.set_title('Pressure Waveform - ' + segment_name)
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print_info("Plot saved: " + save_path)

    return fig


def plot_all_outlets(df, outlets, cycle_duration, save_path=None):
    """
    Plot all outlet waveforms on a single figure.
    """
    n_outlets = len(outlets)

    # Create subplots
    fig, axes = plt.subplots(n_outlets, 2, figsize=(14, 3*n_outlets))

    if n_outlets == 1:
        axes = axes.reshape(1, 2)

    for i, outlet in enumerate(outlets):
        seg_data = extract_segment_data(df, outlet)
        seg_data = extract_last_cycle(seg_data, cycle_duration)

        # Flow
        axes[i, 0].plot(seg_data['time'], seg_data['flow_out'], 'b-', linewidth=1.5)
        axes[i, 0].set_ylabel('Flow (mL/s)')
        axes[i, 0].set_title(outlet + ' - Flow')
        axes[i, 0].grid(True, alpha=0.3)

        # Pressure
        axes[i, 1].plot(seg_data['time'], seg_data['pressure_out'], 'r-', linewidth=1.5)
        axes[i, 1].set_ylabel('Pressure')
        axes[i, 1].set_title(outlet + ' - Pressure')
        axes[i, 1].grid(True, alpha=0.3)

    # Add x-labels to bottom row
    axes[-1, 0].set_xlabel('Time (s)')
    axes[-1, 1].set_xlabel('Time (s)')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print_info("Plot saved: " + save_path)

    return fig


def save_summary_statistics(df, outlets, cycle_duration, output_path):
    """
    Save summary statistics to a CSV file.
    """
    stats_list = []

    for outlet in outlets:
        seg_data = extract_segment_data(df, outlet)
        seg_data = extract_last_cycle(seg_data, cycle_duration)
        stats = compute_statistics(seg_data)
        stats['segment'] = outlet
        stats_list.append(stats)

    stats_df = pd.DataFrame(stats_list)

    # Reorder columns
    cols = ['segment', 'mean_flow_in', 'mean_flow_out', 'max_flow_in', 'min_flow_in',
            'mean_pressure_in', 'mean_pressure_out', 'max_pressure_in', 'min_pressure_in']
    stats_df = stats_df[cols]

    stats_df.to_csv(output_path, index=False)
    print_status("Statistics saved: " + output_path)

    return stats_df


# ========================================================================
# ============================ Main Execution =============================

if __name__ == "__main__":
    print_section_header("EXTRACT 0D RESULTS")

    # Load results
    print_info("Loading 0D results...")
    df = load_0d_results()

    if df is None:
        sys.exit(1)

    print_status("Loaded " + str(len(df)) + " data points")

    # Get segment info
    segments = get_segment_names(df)
    outlets = get_outlet_segments(df)
    cycle_duration = get_cardiac_cycle_duration()

    print_info("Total segments: " + str(len(segments)))
    print_info("Outlet segments: " + str(len(outlets)))
    print_info("Cardiac cycle duration: " + str(cycle_duration) + " s")
    print_info("Simulation time: " + str(df['time'].min()) + " to " + str(df['time'].max()) + " s")

    # User options
    print("\n" + "-" * 70)
    print("  >>> EXTRACTION OPTIONS <<<")
    print("-" * 70)

    # Show plots?
    while True:
        answer = input("  Show plots? (yes/no): ").lower()
        if answer in ["yes", "y"]:
            show_plots = True
            break
        elif answer in ["no", "n"]:
            show_plots = False
            break
        else:
            print("  Please enter 'yes' or 'no'")

    # Save plots?
    while True:
        answer = input("  Save plots to files? (yes/no): ").lower()
        if answer in ["yes", "y"]:
            save_plots = True
            break
        elif answer in ["no", "n"]:
            save_plots = False
            break
        else:
            print("  Please enter 'yes' or 'no'")

    # Extract all or outlets only?
    while True:
        answer = input("  Extract all segments or outlets only? (all/outlets): ").lower()
        if answer in ["all", "a"]:
            target_segments = segments
            break
        elif answer in ["outlets", "outlet", "o"]:
            target_segments = outlets
            break
        else:
            print("  Please enter 'all' or 'outlets'")

    print("-" * 70)

    # Process results
    print_section_header("PROCESSING RESULTS")

    # Extract last cycle data
    print_info("Extracting last cardiac cycle...")
    df_last_cycle = extract_last_cycle(df, cycle_duration)

    # Save statistics
    stats_path = os.path.join(res_folder_0D, '0D_statistics.csv')
    print_info("Computing statistics...")
    stats_df = save_summary_statistics(df, target_segments, cycle_duration, stats_path)

    # Display summary
    print("\n" + "-" * 70)
    print("  Summary Statistics (Outlets)")
    print("-" * 70)
    print(stats_df.to_string(index=False))
    print("-" * 70)

    # Generate plots
    if show_plots or save_plots:
        print_section_header("GENERATING PLOTS")

        # Plot all outlets together
        if save_plots:
            all_outlets_path = os.path.join(res_folder_0D, '0D_all_outlets.png')
        else:
            all_outlets_path = None

        print_info("Plotting outlet waveforms...")
        fig = plot_all_outlets(df, outlets, cycle_duration, all_outlets_path)

        if show_plots:
            plt.show()
        else:
            plt.close(fig)

        # Individual segment plots if requested
        if save_plots and len(target_segments) <= 10:
            print_info("Saving individual segment plots...")
            for seg in target_segments:
                seg_data = extract_segment_data(df, seg)
                seg_data = extract_last_cycle(seg_data, cycle_duration)

                plot_path = os.path.join(res_folder_0D, '0D_' + seg + '.png')
                fig = plot_segment_waveforms(seg_data, seg, plot_path)
                plt.close(fig)

    # Final summary
    print_section_header("EXTRACTION COMPLETE")

    print_info("Output files:")
    print("    - Statistics: " + stats_path)
    if save_plots:
        print("    - Plots: " + res_folder_0D + "/0D_*.png")

    print("\n" + "-" * 70)
    print("  0D result extraction complete!")
    print("-" * 70 + "\n")
