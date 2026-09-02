"""
Interactive inflow waveform editor (matplotlib): drag control points to
shape one cardiac cycle, enter the heart rate, close the window.
"""
import importlib.util
import os
import sys
from typing import Optional, Tuple

import numpy as np


def _has_display() -> bool:
    if sys.platform.startswith('linux'):
        return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
    return True


def _setup_backend():
    import matplotlib
    if importlib.util.find_spec("PyQt5") or importlib.util.find_spec("PySide2") or \
            importlib.util.find_spec("PyQt6") or importlib.util.find_spec("PySide6"):
        matplotlib.use('QtAgg')
    else:
        matplotlib.use('TkAgg')


class _DraggablePoints:
    def __init__(self, ax, x, y, update):
        self.ax, self.x, self.y, self.update = ax, x, y, update
        self.canvas = ax.figure.canvas
        self.pts = ax.scatter(x, y, c='red', s=90, picker=True, pickradius=12, zorder=5)
        self._ind = None
        # keep the connection ids: the object must stay alive for the callbacks to fire
        self._cids = [self.canvas.mpl_connect('pick_event', self.on_pick),
                      self.canvas.mpl_connect('motion_notify_event', self.on_motion),
                      self.canvas.mpl_connect('button_release_event', self.on_release)]

    def on_pick(self, event):
        if event.artist is self.pts:
            self._ind = event.ind[0]

    def on_motion(self, event):
        if self._ind is None or event.inaxes is not self.ax:
            return
        if self._ind in (0, len(self.x) - 1):
            self.y[0] = self.y[-1] = event.ydata      # periodic
        else:
            self.y[self._ind] = event.ydata
        self.pts.set_offsets(np.c_[self.x, self.y])
        self.update()
        self.canvas.draw_idle()

    def on_release(self, event):
        self._ind = None


def edit_waveform(heart_rate_bpm: float = 60.0, points_per_cycle: int = 1200,
                  peak_flow: Optional[float] = None, initial: Optional[Tuple[np.ndarray, np.ndarray]] = None
                  ) -> Tuple[np.ndarray, np.ndarray]:
    """
    Open the editor and return (time [s], flow [mL/s]) for one cycle,
    sampled at points_per_cycle. `peak_flow` sets the axis range;
    `initial` (t, q) preloads a waveform.
    """
    if not _has_display():
        raise RuntimeError("the waveform editor needs a display; set inflow.source to 'file' "
                           "and provide inflow.file instead")
    _setup_backend()
    import matplotlib.pyplot as plt
    from matplotlib.widgets import TextBox
    import matplotlib.ticker as mticker
    from scipy.interpolate import interp1d

    x_ctrl = np.linspace(0, 1, 20)
    if initial is not None:
        t0, q0 = initial
        y_ctrl = np.interp(x_ctrl, (t0 - t0[0]) / (t0[-1] - t0[0]), q0)
        peak_flow = peak_flow or float(np.abs(q0).max())
    else:
        y_ctrl = np.zeros_like(x_ctrl)
    upper = 1.25 * peak_flow if peak_flow else 500.0
    lower = -0.25 * peak_flow if peak_flow else -100.0

    fig, ax = plt.subplots(figsize=(9, 5.5))
    fig.subplots_adjust(bottom=0.25)
    x_dense = np.linspace(0, 1, 500)
    f = interp1d(x_ctrl, y_ctrl, kind='quadratic', fill_value='extrapolate')
    line, = ax.plot(x_dense, f(x_dense), lw=2)

    def refresh():
        g = interp1d(x_ctrl, y_ctrl, kind='quadratic', fill_value='extrapolate')
        line.set_data(x_dense, g(x_dense))

    dragger = _DraggablePoints(ax, x_ctrl, y_ctrl, refresh)   # must outlive plt.show(): it owns the callbacks
    ax.set_title('Drag the red points to shape one cardiac cycle (first and last point are tied).\n'
                 'Set heart rate and axis range below, press Enter in each box, then close the window.')
    ax.grid(True, alpha=0.3)
    ax.set_ylabel('Flow [mL/s]')
    ax.set_xlabel('Cycle')
    ax.set_ylim(lower, upper)
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, p: '%d%%' % round(v * 100)))

    state = {'hr': float(heart_rate_bpm)}
    box = TextBox(plt.axes([0.25, 0.08, 0.15, 0.05]), 'Heart rate [bpm]: ', initial='%g' % heart_rate_bpm)

    def on_hr(text):
        try:
            v = float(text)
            if v <= 0:
                raise ValueError
            state['hr'] = v
            box.text_disp.set_color('black')
        except ValueError:
            box.text_disp.set_color('red')
    box.on_submit(on_hr)

    # axis range: the peak flow you expect, so the curve has room
    ybox = TextBox(plt.axes([0.72, 0.08, 0.15, 0.05]), 'Peak flow axis [mL/s]: ', initial='%g' % (upper / 1.25))

    def on_ymax(text):
        try:
            v = float(text)
            if v <= 0:
                raise ValueError
            ax.set_ylim(-0.25 * v, 1.25 * v)
            fig.canvas.draw_idle()
            ybox.text_disp.set_color('black')
        except ValueError:
            ybox.text_disp.set_color('red')
    ybox.on_submit(on_ymax)
    plt.show()
    del dragger

    x_norm, y = line.get_data()
    T = 60.0 / state['hr']
    t = np.linspace(0.0, T, int(points_per_cycle))
    q = interp1d(x_norm * T, y, kind='quadratic', fill_value='extrapolate')(t)
    return t, q
