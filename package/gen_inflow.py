import numpy as np
import pdb
import matplotlib
import importlib.util

# if *either* Qt binding is available, go Qt5Agg, otherwise TkAgg
if importlib.util.find_spec("PyQt5") or importlib.util.find_spec("PySide2"):
    matplotlib.use('Qt5Agg')
else:
    matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d
from matplotlib.widgets import TextBox
import matplotlib.ticker as mticker
import os
from __init__ import *


# ========================================================================
# ============================ CFL-based Timestep Computation ============
# ========================================================================

def compute_timesteps_from_cfl(peak_flow, hr, cfl=0.9, min_timesteps=1200):
    """
    Compute the number of timesteps per cardiac cycle based on CFL constraint.

    For implicit solvers, CFL = 0.9 is typically stable.

    CFL = velocity * dt / dx

    Args:
        peak_flow: Peak flow rate in mL/s
        hr: Heart rate in bpm
        cfl: Target CFL number (default 0.9 for implicit solver)
        min_timesteps: Minimum timesteps for numerical accuracy (default 1200)

    Returns:
        int: Number of timesteps per cardiac cycle
    """
    # Read cap areas from preprocessing
    cap_areas_file = os.path.join(caps_folder, 'cap_areas.txt')

    min_cap_area = None
    if os.path.exists(cap_areas_file):
        try:
            with open(cap_areas_file, 'r') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        try:
                            area = float(parts[1])
                            if min_cap_area is None or area < min_cap_area:
                                min_cap_area = area
                        except ValueError:
                            continue
        except Exception as e:
            print(f"  [Warning] Could not read cap areas: {e}")

    # If we couldn't get cap areas, use a conservative default
    if min_cap_area is None or min_cap_area <= 0:
        print("  [Info] Cap areas not available, using default timesteps")
        return max(min_timesteps, 2000)

    # Compute peak velocity (flow / area)
    # Convert: flow in mL/s = cm³/s, area in cm² -> velocity in cm/s
    peak_velocity = abs(peak_flow) / min_cap_area  # cm/s

    # Characteristic length scale (approximate from cap area)
    # dx ~ sqrt(area) gives a rough mesh scale
    dx = np.sqrt(min_cap_area)  # cm

    # Cycle duration
    cycle_duration = 60.0 / hr  # seconds

    # CFL = velocity * dt / dx
    # dt = CFL * dx / velocity
    # n_timesteps = cycle_duration / dt = cycle_duration * velocity / (CFL * dx)

    if peak_velocity > 0:
        dt_cfl = cfl * dx / peak_velocity
        n_timesteps = int(np.ceil(cycle_duration / dt_cfl))
    else:
        n_timesteps = min_timesteps

    # Ensure minimum timesteps for accuracy
    n_timesteps = max(n_timesteps, min_timesteps)

    # Round up to nearest 100 for cleaner numbers
    n_timesteps = int(np.ceil(n_timesteps / 100) * 100)

    print(f"  -> Timesteps computed automatically based on CFL constraint:")
    print(f"     Peak velocity: {peak_velocity:.1f} cm/s")
    print(f"     Characteristic length: {dx:.3f} cm")
    print(f"     CFL number: {cfl}")
    print(f"     Timesteps per cycle: {n_timesteps}")

    return n_timesteps

class DraggablePoints:
    def __init__(self, ax, x, y, line, update_callback):
        self.ax = ax
        self.canvas = ax.figure.canvas
        self.x = x
        self.y = y
        self.line = line
        self.update = update_callback

        # scatter with a pick radius of 10 points
        self.pts = ax.scatter(x, y, c='red', s=100, picker=10)
        self._ind = None

        # hook into pick/motion/release
        self.canvas.mpl_connect('pick_event',           self.on_pick)
        self.canvas.mpl_connect('motion_notify_event',  self.on_motion)
        self.canvas.mpl_connect('button_release_event', self.on_release)

    def on_pick(self, event):
        if event.artist is not self.pts:
            return
        self._ind = event.ind[0]

    def on_motion(self, event):
        if self._ind is None or event.inaxes is not self.ax:
            return
        ydata = event.ydata
        # enforce first and last point have same y-value
        if self._ind == 0 or self._ind == len(self.x) - 1:
            self.y[0] = self.y[-1] = ydata
        else:
            self.y[self._ind] = ydata
        self.pts.set_offsets(np.c_[self.x, self.y])
        self.update()
        self.canvas.draw_idle()

    def on_release(self, event):
        self._ind = None



def launch(flow_lower=-100, flow_upper=500):
    """
    Launch the interactive inflow waveform editor.

    Args:
        flow_lower: Lower bound for flow rate (mL/s)
        flow_upper: Upper bound for flow rate (mL/s)
    """
    # control points over [0, 1]
    x_ctrl = np.linspace(0, 1, 20)
    y_ctrl = np.zeros_like(x_ctrl)

    fig, ax = plt.subplots()
    fig.subplots_adjust(bottom=0.25)

    # dense sampling for smooth curve
    x_dense = np.linspace(0, 1, 500)
    interp_func = interp1d(x_ctrl, y_ctrl, kind='quadratic', fill_value='extrapolate')
    line, = ax.plot(x_dense, interp_func(x_dense), lw=2)

    def refresh():
        f = interp1d(x_ctrl, y_ctrl, kind='quadratic', fill_value='extrapolate')
        line.set_data(x_dense, f(x_dense))
        fig.canvas.draw_idle()

    # draggable points keeper
    global draggable
    draggable = DraggablePoints(ax, x_ctrl, y_ctrl, line, refresh)

    # title, grid, labels
    ax.set_title('Drag the red control points to reshape the curve. Close when done.')
    ax.grid(True)
    ax.set_ylabel('Flow rate [mL/s]')
    ax.set_xlabel('Normalized Time [0% to 100%]')
    ax.set_ylim(flow_lower, flow_upper)
    ax.set_xlim(0, 1)
    ax.set_xticks(np.linspace(0, 1, 11))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(
        lambda val, pos: '{:.0f}%'.format(val * 100)
    ))

    # prepare variables to capture validated inputs
    hr_val = None
    ts_val = 'auto'  # Default to auto

    # --- HR box ---
    axbox1 = plt.axes([0.2, 0.08, 0.15, 0.04])
    text_box1 = TextBox(axbox1, 'HR [bpm]:')
    def submit_hr(text):
        nonlocal hr_val
        try:
            hr = float(text)
            if hr <= 0:
                raise ValueError("HR must be positive.")
            hr_val = hr
            text_box1.text_disp.set_color('black')
        except Exception as e:
            hr_val = None
            text_box1.text_disp.set_color('red')
            print(f"[HR] invalid input `{text}`: {e}. Please enter a positive number.")
    text_box1.on_submit(submit_hr)

    # --- Timesteps box (auto or user-defined) ---
    axbox2 = plt.axes([0.65, 0.08, 0.12, 0.04])
    text_box2 = TextBox(axbox2, '# Timesteps (auto or number):', initial='auto')
    def submit_ts(text):
        nonlocal ts_val
        text = text.strip().lower()
        if text == '' or text == 'auto':
            ts_val = 'auto'
            text_box2.text_disp.set_color('blue')
            print("[Timesteps] Will be computed automatically based on CFL constraint.")
        else:
            try:
                ts = int(text)
                if ts <= 0:
                    raise ValueError("Must be > 0.")
                if ts < 1200:
                    print("[Timesteps] Warning: recommended >= 1200 for good resolution.")
                ts_val = ts
                text_box2.text_disp.set_color('black')
            except Exception as e:
                ts_val = 'auto'
                text_box2.text_disp.set_color('red')
                print(f"[Timesteps] invalid input `{text}`: {e}. Using auto.")
    text_box2.on_submit(submit_ts)

    plt.show()
    return hr_val, ts_val, line


def postprocess_inflow(hr, ts_val, curve_line, peak_flow=None):
    """
    Process the inflow waveform.

    Args:
        hr: Heart rate in bpm
        ts_val: Timesteps - either 'auto' or an integer
        curve_line: Matplotlib line object with waveform data
        peak_flow: Expected peak flow for CFL computation (optional)
    """
    # parse inputs with defaults
    hr = int(hr) if hr else 60

    print('  Heart Rate: {} bpm'.format(hr))

    # extract your plotted data
    x_norm, y = curve_line.get_data()

    # Get peak flow from the waveform if not provided
    if peak_flow is None:
        peak_flow = max(abs(y.max()), abs(y.min()))

    # Determine timesteps - auto or user-defined
    if ts_val == 'auto' or ts_val is None:
        steps = compute_timesteps_from_cfl(peak_flow, hr)
    else:
        steps = int(ts_val)
        print(f'  Timesteps per cycle: {steps} (user-defined)')

    # compute cycle length and time axis
    cyc = 60.0 / hr
    time = np.linspace(0, cyc, steps)

    # build interpolator in real seconds
    x_time = x_norm * cyc
    f_time = interp1d(x_time, y, kind='quadratic', fill_value='extrapolate')

    # sample to get your inflow array
    flow = f_time(time)

    return time, flow


def save_inflow_file(time, flow, filename='inflow_1d.flow'):
    # save the inflow data to a file
    with open(os.path.join(master_folder, filename), 'w') as f:
        #f.write("# Time [s]  Flow [mL/s]\n")
        for t, q in zip(time, flow):
            f.write('{:.6f} {:.6f}\n'.format(t, q))


def generate_inflow_file(flow_lower=-100, flow_upper=500, peak_flow=None):
    """Generate inflow file using interactive GUI editor."""
    hr, ts_val, curve_line = launch(flow_lower, flow_upper)
    time, flow = postprocess_inflow(hr, ts_val, curve_line, peak_flow)
    save_inflow_file(time, flow)


def get_flow_bounds_from_user():
    """
    Ask user about expected peak flow velocity and compute appropriate bounds.
    Returns (lower_bound, upper_bound, peak_flow) with 25% margin.
    """
    print("\n" + "=" * 70)
    print("  INFLOW WAVEFORM SETUP")
    print("=" * 70)
    print("")
    print("  Before creating the inflow waveform, we need to know the expected")
    print("  peak flow rate for your model.")
    print("")
    print("  Typical peak flow rates:")
    print("    - Aorta: 300-500 mL/s")
    print("    - Carotid artery: 5-15 mL/s")
    print("    - Coronary artery: 1-5 mL/s")
    print("    - Cerebral artery: 2-10 mL/s")
    print("")

    while True:
        try:
            peak_flow = input("  What is your expected peak flow rate? (mL/s): ").strip()
            peak_flow = float(peak_flow)
            if peak_flow <= 0:
                print("  Please enter a positive number.")
                continue
            break
        except ValueError:
            print("  Invalid input. Please enter a number (e.g., 400).")

    # Calculate bounds with 25% margin
    flow_upper = peak_flow * 1.25
    flow_lower = -peak_flow * 0.25  # Allow some negative (backflow)

    print("")
    print(f"  -> Flow rate bounds set to: {flow_lower:.1f} to {flow_upper:.1f} mL/s")
    print(f"     (Your peak flow {peak_flow:.1f} mL/s + 25% margin)")
    print("")

    return flow_lower, flow_upper, peak_flow


if __name__ == '__main__':
    print("\n" + "=" * 70)
    print("  CARDIAC INFLOW WAVEFORM")
    print("=" * 70)
    print("")
    print("  The inflow waveform defines how blood flows into your model")
    print("  over one cardiac cycle.")
    print("")
    print("  Would you like to create a new inflow waveform using the")
    print("  interactive visual editor?")
    print("")
    print("    Type 'yes' to open the interactive waveform editor")
    print("    Type 'no' if you already have an inflow file (inflow_1d.flow)")
    print("")

    while True:
        user_choice = input("  Create new inflow waveform? (yes/no): ").strip().lower()
        if user_choice in ['yes', 'no']:
            break
        print("  Please type 'yes' or 'no'.")

    if user_choice == 'yes':
        # Get flow bounds from user
        flow_lower, flow_upper, peak_flow = get_flow_bounds_from_user()

        print("  Opening interactive waveform editor...")
        print("  -> Drag the red control points to shape your flow waveform")
        print("  -> Enter heart rate in the text box")
        print("  -> Timesteps: leave as 'auto' for CFL-based computation, or enter a number")
        print("  -> Close the window when done")
        print("")

        generate_inflow_file(flow_lower, flow_upper, peak_flow)
        print("\n  Inflow waveform saved to: {}".format(
            os.path.join(master_folder, 'inflow_1d.flow')))
    else:
        inflow_file_path = os.path.join(master_folder, 'inflow_1d.flow')
        if os.path.exists(inflow_file_path):
            print("")
            print(f"  Using existing inflow file: {inflow_file_path}")
        else:
            print("")
            print(f"  [WARNING] Inflow file not found: {inflow_file_path}")
            print("  Please make sure your inflow file is named 'inflow_1d.flow'")
            print("  and placed in the master folder before continuing.")