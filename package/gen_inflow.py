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



def launch():
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
    ax.set_ylim(-100, 500)
    ax.set_xlim(0, 1)
    ax.set_xticks(np.linspace(0, 1, 11))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(
        lambda val, pos: '{:.0f}%'.format(val * 100)
    ))

    # prepare variables to capture validated inputs
    hr_val = None
    ts_val = None   # timesteps per cycle

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
    axbox2 = plt.axes([0.79, 0.08, 0.15, 0.04])
    text_box2 = TextBox(axbox2, '# Timesteps per cycle (rec >= 1200):')
    def submit_ts(text):
        nonlocal ts_val
        try:
            ts = int(text)
            if ts <= 0:
                raise ValueError("Must be > 0.")
            if ts < 1200:
                print("[Timesteps] Warning: recommended >= 1200 for good resolution.")
            ts_val = ts
            text_box2.text_disp.set_color('black')
        except Exception as e:
            ts_val = None
            text_box2.text_disp.set_color('red')
            print(f"[Timesteps] invalid input `{text}`: {e}. Please enter a positive integer.")
    text_box2.on_submit(submit_ts)

    plt.show()
    return hr_val, ts_val, line


def postprocess_inflow(hr, steps, curve_line):
    # parse inputs with defaults
    hr    = int(hr)    if hr    else 60
    steps = int(steps) if steps else 1200

    print('Heart Rate: {} bpm'.format(hr))
    print('Steps per cycle: {}'.format(steps))

    # extract your plotted data
    x_norm, y = curve_line.get_data()  # same as get_xdata()/get_ydata()

    # compute cycle length and time axis
    cyc  = 60.0 / hr
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


def generate_inflow_file():
    hr, steps, curve_line = launch()
    time, flow = postprocess_inflow(hr, steps, curve_line)
    save_inflow_file(time, flow)

if __name__ == '__main__':
    print('\n')
    print("Now, you are going to create an inflow file from the GUI editor.")
    print('Do you have an existing inflow file you wish to use? (yes/no)")')
          
    inflow_file_exists = input().strip().lower()

    if inflow_file_exists == 'yes':
        print('Make sure the inflow file is in the master folder and named "inflow_1d.flow"')
        inflow_file_path = os.path.join(master_folder, 'inflow_1d.flow')
        print("Using existing inflow file: {}".format(inflow_file_path))
    else:
        generate_inflow_file()