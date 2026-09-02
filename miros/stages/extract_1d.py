"""extract_1d: last-cycle CSV/VTP(/VTU) from the OneDSolver outputs, pressure also in mmHg."""
import shutil
from pathlib import Path

import numpy as np

from ..io import inflow as IO
from ..io import zerod as Z
from ..manifest import file_hash, value_hash
from ..ui import console


def inputs(case):
    d = {'oned_input': file_hash(case.oned_input), 'log': file_hash(case.results_1d / 'onedsolver.log'),
         'centerlines': file_hash(case.centerlines), 'outputs': value_hash(case.config.section('outputs'))}
    vtu = case.mesh_complete_dir / 'mesh-complete.mesh.vtu'
    if case.config.outputs.volume_projection and vtu.exists():
        d['volume'] = file_hash(vtu)
    return d


def outputs(case):
    return [case.results_1d / 'extracted_results_flow.csv', case.results_1d / 'extracted_results.vtp']


def _time_range(case):
    dt = nst = None
    for line in open(case.oned_input):
        tok = line.split()
        if tok and tok[0] == 'SOLVEROPTIONS':
            dt, nst = float(tok[1]), int(tok[3])
            break
    T = IO.cycle_duration(case.inflow_work)
    n = int(dt * nst / T + 1e-6)
    return "%s,%s" % ((n - 1) * T, n * T) if n >= 1 else "0,%s" % (dt * nst)


def _to_mmhg(results: Path):
    import pandas as pd
    import vtk
    from vtk.util.numpy_support import numpy_to_vtk as n2v, vtk_to_numpy as v2n
    for csv in results.glob('*pressure*.csv'):
        if 'mmHg' in csv.name:
            continue
        df = pd.read_csv(csv)
        for col in df.columns:
            if col.lower() != 'time':
                df[col] = df[col] / Z.MMHG_TO_CGS
        df.to_csv(csv.with_name(csv.stem + '_mmHg.csv'), index=False)
    for pattern, reader_cls, writer_cls in (('*.vtp', vtk.vtkXMLPolyDataReader, vtk.vtkXMLPolyDataWriter),
                                            ('*.vtu', vtk.vtkXMLUnstructuredGridReader, vtk.vtkXMLUnstructuredGridWriter)):
        for f in results.glob(pattern):
            if not f.name.startswith('extracted_results'):
                continue
            r = reader_cls(); r.SetFileName(str(f)); r.Update()
            data = r.GetOutput()
            pdata = data.GetPointData()
            names = [pdata.GetArrayName(i) for i in range(pdata.GetNumberOfArrays())]
            for name in names:
                if 'pressure' in name.lower() and 'mmHg' not in name:
                    arr = n2v(v2n(pdata.GetArray(name)) / Z.MMHG_TO_CGS, deep=True)
                    arr.SetName(name.replace('pressure', 'pressure_mmHg'))
                    pdata.AddArray(arr)
            w = writer_cls(); w.SetFileName(str(f)); w.SetInputData(data); w.Write()


def run(case):
    from ..rom_extract.extract_results import run as extract_run
    from ..rom_extract.manage import init_logging
    res = case.results_1d
    shutil.copy(case.oned_input, res / case.oned_input.name)
    shutil.copy(case.oned_model, res / case.oned_model.name)
    for old in list(res.glob('extracted_results*')) + list(res.glob('*_mmHg.csv')):
        old.unlink()
    cfg = dict(model_order=1, results_directory=str(res), solver_file_name=case.oned_input.name,
               output_directory=str(res), output_file_name='extracted_results', output_format='csv',
               time_range=_time_range(case), data_names='flow,pressure,area', outlet_segments='true',
               centerlines_file=str(case.centerlines), plot='off', display_geometry='off')
    vtu = case.mesh_complete_dir / 'mesh-complete.mesh.vtu'
    vtp = case.mesh_complete_dir / 'mesh-complete.exterior.vtp'
    if case.config.outputs.volume_projection and vtu.exists() and vtp.exists():
        cfg['volume_mesh_file'] = str(vtu)
        cfg['walls_mesh_file'] = str(vtp)
    init_logging(str(res))
    msg = extract_run(**cfg)
    console.info(str(msg).strip())
    _to_mmhg(res)
    console.info("files: %s" % ', '.join(sorted(f.name for f in res.glob('extracted_results*'))))
    return outputs(case)
