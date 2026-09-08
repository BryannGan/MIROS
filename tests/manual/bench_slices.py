"""How long a slice view costs: cutting polygonal slices against three image actors.

Run it with the MIROS environment and an offscreen Qt platform:

    QT_QPA_PLATFORM=offscreen python tests/manual/bench_slices.py

Paths come from the environment so the script survives a new machine:
    MIROS_REPO       the repo (default: two directories up from this file)
    MIROS_TUTORIAL   a SeqSeg tutorial case to work from (case.yaml + work/)
    MIROS_IMAGE      a CT or MR volume to load
"""
import os
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get('MIROS_REPO', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
TUTORIAL = Path(os.environ.get('MIROS_TUTORIAL', REPO / 'examples' / 'seqseg_tutorial'))
IMAGE = Path(os.environ.get('MIROS_IMAGE', TUTORIAL / 'input' / '0110_0001.mha'))
import numpy as np, pyvista as pv, vtk, SimpleITK as sitk
from qtpy import QtWidgets
from pyvistaqt import QtInteractor

p = str(IMAGE)
img = sitk.ReadImage(p); arr = sitk.GetArrayFromImage(img)
grid = pv.ImageData(dimensions=img.GetSize(), spacing=img.GetSpacing(), origin=img.GetOrigin())
grid.point_data['intensity'] = arr.ravel(order='C').astype(np.float32)
print('volume', grid.dimensions, '%.0f MB' % (grid.n_points * 4 / 1e6))
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
w = QtWidgets.QWidget(); w.resize(900, 700)
pl = QtInteractor(w); pl.interactor.resize(900, 700); w.show(); app.processEvents()
lo, hi = np.array(grid.bounds[0::2]), np.array(grid.bounds[1::2])
pos = 0.5 * (lo + hi)
vals = grid.point_data['intensity']
clim = (float(np.percentile(vals, 1)), float(np.percentile(vals, 99)))

def draw_slices():
    x, y, z = pos
    for n, nm in (('x', 'slice_x'), ('y', 'slice_y'), ('z', 'slice_z')):
        pl.add_mesh(grid.slice(normal=n, origin=(x, y, z)), name=nm, cmap='gray', clim=clim, show_scalar_bar=False)
    pl.render()

t0 = time.time(); draw_slices(); print('current: first draw %.2f s' % (time.time() - t0))
t0 = time.time()
for k in range(5):
    pos[2] = lo[2] + (0.3 + 0.05 * k) * (hi[2] - lo[2]); draw_slices()
print('current: %.0f ms per slider step' % (1000 * (time.time() - t0) / 5))

pl.clear()
# image actors: the mapper uploads one plane, moving a slice only changes the display extent
dims = np.array(grid.dimensions) - 1
actors = []
for axis in range(3):
    a = vtk.vtkImageActor()
    a.GetMapper().SetInputData(grid)
    a.GetProperty().SetColorWindow(clim[1] - clim[0]); a.GetProperty().SetColorLevel(0.5 * sum(clim))
    pl.add_actor(a)
    actors.append(a)

def set_index(axis, k):
    e = [0, dims[0], 0, dims[1], 0, dims[2]]
    e[2 * axis] = e[2 * axis + 1] = int(k)
    actors[axis].SetDisplayExtent(*e)

t0 = time.time()
for axis in range(3):
    set_index(axis, dims[axis] // 2)
pl.reset_camera(); pl.render(); print('actors: first draw %.2f s' % (time.time() - t0))
t0 = time.time()
for k in range(20):
    set_index(2, int(dims[2] * (0.3 + 0.02 * k))); pl.render()
print('actors: %.0f ms per slider step' % (1000 * (time.time() - t0) / 20))

# picking cost on each representation
pk = vtk.vtkCellPicker(); pk.SetTolerance(0.005)
t0 = time.time(); ok = pk.Pick(450, 350, 0, pl.renderer); dt = time.time() - t0
print('pick on image actors: %s %.0f ms %s' % (bool(ok), 1000 * dt, np.round(pk.GetPickPosition(), 2)))
