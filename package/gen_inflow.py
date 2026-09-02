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


# Number of time points per cardiac cycle written to the inflow file.
# The 0D and 1D solvers are implicit, so this is a resolution choice rather
# than a stability (CFL) constraint; 1200 resolves a cardiac waveform well.
DEFAULT_TIMESTEPS_PER_CYCLE = 1200

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
    ts_val = DEFAULT_TIMESTEPS_PER_CYCLE

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

    # --- Timesteps box ---
    axbox2 = plt.axes([0.65, 0.08, 0.12, 0.04])
    text_box2 = TextBox(axbox2, '# Timesteps per cycle:', initial=str(DEFAULT_TIMESTEPS_PER_CYCLE))
    def submit_ts(text):
        nonlocal ts_val
        text = text.strip()
        try:
            ts = int(text) if text else DEFAULT_TIMESTEPS_PER_CYCLE
            if ts <= 0:
                raise ValueError("Must be > 0.")
            if ts < 600:
                print("[Timesteps] Warning: fewer than 600 points per cycle may under-resolve the waveform.")
            ts_val = ts
            text_box2.text_disp.set_color('black')
        except Exception as e:
            ts_val = DEFAULT_TIMESTEPS_PER_CYCLE
            text_box2.text_disp.set_color('red')
            print(f"[Timesteps] invalid input `{text}`: {e}. Using {DEFAULT_TIMESTEPS_PER_CYCLE}.")
    text_box2.on_submit(submit_ts)

    plt.show()
    return hr_val, ts_val, line


def postprocess_inflow(hr, ts_val, curve_line):
    """
    Resample the drawn waveform onto one cardiac cycle.

    Args:
        hr: Heart rate in bpm
        ts_val: Time points per cycle (int)
        curve_line: Matplotlib line object with waveform data
    """
    # parse inputs with defaults
    hr = int(hr) if hr else 60

    print('  Heart Rate: {} bpm'.format(hr))

    # extract your plotted data
    x_norm, y = curve_line.get_data()

    steps = int(ts_val) if ts_val else DEFAULT_TIMESTEPS_PER_CYCLE
    print(f'  Timesteps per cycle: {steps}')

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


def generate_inflow_file(flow_lower=-100, flow_upper=500):
    """Generate inflow file using interactive GUI editor."""
    hr, ts_val, curve_line = launch(flow_lower, flow_upper)
    time, flow = postprocess_inflow(hr, ts_val, curve_line)
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
        print("  -> Time steps per cycle: default " + str(DEFAULT_TIMESTEPS_PER_CYCLE) + "; change only if you need finer output")
        print("  -> Close the window when done")
        print("")

        generate_inflow_file(flow_lower, flow_upper)
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