from sv import *
from sv_rom_simulation import *
from sv_auto_lv_modeling.modeling.src import meshing as svmeshtool
import numpy as np
import pdb
import vtk
from vtk.util import numpy_support
from vtk.util.numpy_support import vtk_to_numpy as v2n
from vtk.util.numpy_support import numpy_to_vtk as n2v
import os 
import shutil
import time
import sys
import csv
import subprocess
import configparser

def write_text(filename: str, content: str, mode: str = 'w') -> None:
    """
    Write text content to a file.

    Parameters:
    - filename: Path to the file you want to write.
    - content:  Text to write into the file.
    - mode:     File mode; 'w' to overwrite (default), 'a' to append.
    """
    try:
        with open(filename, mode, encoding='utf-8') as file:
            file.write(content)
    except OSError as e:
        # Use .format() instead of f-string for older Python versions
        print("Error writing to file {!r}: {}".format(filename, e))


def write_caps_and_wall(fpath,modeler):
        # total_face_ids = modeler.get_face_ids()
        # get_cap_ids = modeler.identify_caps()
        # keep_true_cap = [i+1 for i in range(len(get_cap_ids)) if get_cap_ids[i] == True]
        # for i , id in enumerate(keep_true_cap):
        #     write_polydata(os.path.join(fpath,'cap_'+str(id)+'.vtp'),modeler.get_face_polydata(id))
        # print("Caps written to: ", fpath)

        # wall_ids = [i+1 for i in range(len(total_face_ids)) if i not in keep_true_cap]
        # print("Total face ids: ", total_face_ids)
        
        # print('cap ids: ', keep_true_cap)
        # print("Wall ids: ", wall_ids)

        
        # id 0 is the wall
        total_face_ids = modeler.get_face_ids()
        wall_ids = total_face_ids[0]
        print("Total face ids: ", total_face_ids)
        print("Wall ids: ", wall_ids)
        cap_ids = total_face_ids[1:]  # All other ids are caps
        print("Cap ids: ", cap_ids)
        for i in cap_ids:
            write_polydata(os.path.join(fpath, 'cap_' + str(i) + '.vtp'), modeler.get_face_polydata(i))
        for i in [wall_ids]:
            write_polydata(os.path.join(fpath, 'wall.vtp'), modeler.get_face_polydata(i))
        # for i in total_face_ids:
        #       write_polydata(os.path.join(fpath, 'face_' + str(i) + '.vtp'), modeler.get_face_polydata(i))
        cap_names = [f for f in os.listdir(fpath)
             if f.startswith('cap_') and f.endswith('.vtp')]
        
        for i, name in enumerate(cap_names):
                name_no_ext = os.path.splitext(name)[0]          # strip '.vtp'
                mode = 'w' if i == 0 else 'a'                    # write first, then append
                write_text(os.path.join(os.path.dirname(fpath), 'centerlines_outlets.dat'),
                        name_no_ext + '\n',
                        mode)
                
                
def create_rcr_bc_template(cap_folder_path, save_to):
    # extract filenames that start with 'cap_'
    cap_filenames = [f for f in os.listdir(cap_folder_path) if f.startswith('cap_') and f.endswith('.vtp')]
    cap_names = [os.path.splitext(fn)[0] for fn in cap_filenames]
    # sort the cap names
    cap_names.sort()
    # write out the line separator
    write_text(save_to,'2\n', 'w')
    for i in cap_names:
        # write out the cap name
        write_text(save_to,'2\n', 'a')
        write_text(save_to, i + '\n', 'a')
        write_text(save_to, '<R_proximal>\n', 'a')
        write_text(save_to, '<capacitance>\n', 'a') 
        write_text(save_to, '<R_distal>\n', 'a')
        write_text(save_to, '0.0 0.0\n', 'a')
        write_text(save_to, '1.0 0.0\n', 'a')
        

def get_inlet_cap_name(caps_folder):
    """
    Ask the user for a cap name (without “.vtp”) and
    only return once we have a file that actually exists.
    """
    while True:
        name = raw_input("Please enter the name of the cap to be used as inlet (e.g., cap_1): ") \
               if sys.version_info < (3, 0) else input(
                   "Please enter the name of the cap to be used as inlet (e.g., cap_1): "
               )
        path = os.path.join(caps_folder, name + '.vtp')
        if os.path.exists(path):
            os.rename(path, os.path.join(caps_folder, 'inlet.vtp'))
            print("Inlet cap set as '{0}.vtp' and renamed as 'inlet.vtp'\n".format(name))
            return
        else:
            # using .format() instead of f-string
            print("Cap file '{0}.vtp' does not exist. Please check the name and try again.\n".format(name))
    # rename path to inlet.vtp
    # later centerlines_outlets.dat will automatically be changed (remove the cap name of the inlet)

def compute_surface_area(polydata: vtk.vtkPolyData) -> float:
    """
    Compute the surface area of a vtkPolyData mesh.

    Parameters
    ----------
    polydata : vtk.vtkPolyData
        The input mesh. Can be from vtkPlaneSource, a reader (e.g. .vtp),
        or any other filter producing vtkPolyData.

    Returns
    -------
    float
        Total surface area of the mesh.
    """
    # 1) Triangulate the mesh (MassProperties works on triangles)
    triangleFilter = vtk.vtkTriangleFilter()
    triangleFilter.SetInputData(polydata)
    triangleFilter.Update()

    # 2) Compute surface area
    mass = vtk.vtkMassProperties()
    mass.SetInputConnection(triangleFilter.GetOutputPort())
    mass.Update()

    return mass.GetSurfaceArea()


def write_helper_txt(master_folder,caps_folder):
    helper_txt = os.path.join(master_folder, 'model_info.txt')
    for i in range(len(os.listdir(caps_folder))):
        cap_file = os.listdir(caps_folder)[i]
        if cap_file.startswith('cap_') and cap_file.endswith('.vtp'):
            cap_polydata = read_surface(os.path.join(caps_folder, cap_file), 'vtp', None)
            area = compute_surface_area(cap_polydata)
            cap_name = os.path.splitext(cap_file)[0]
            if i == 0:
                write_text(
                                helper_txt,
                                'Cap {} area: {}\n'.format(cap_name, area),
                                'w'
                                )
            else:
                write_text(
                                helper_txt,
                                'Cap {} area: {}\n'.format(cap_name, area),
                                'a'
                                )
    write_text(helper_txt, 'for more information about rcr, consult other resources such as https://www.youtube.com/watch?v=3QRYhTRz9nw', mode = 'a')
    write_text(helper_txt, 'total Resistance = R_proximal + R_distal = P_mean/Q_mean', mode = 'a')
    write_text(helper_txt, 'characteristic fill time of compliance = C * R_distal', mode = 'a')
    return helper_txt

def get_number_of_timesteps(n_cyc,inflow_file):
    # read the number of lines in the inflow file
    with open(inflow_file, 'r') as f:
        num_lines = sum(1 for line in f)
        

    num_time_steps = n_cyc * num_lines
    while True:
        if num_time_steps < num_lines:
            print('Number of time steps is trivial')
            print("Please check the inflow file or adjust the number of cycles.")
            n_cyc = int(input("Enter the number of cycles: "))
        else: 
            #print("The number of time steps is: ", num_time_steps)
            return num_time_steps
        

def get_timestep_size(inflow_file):
    """
    Get the time step size from the inflow file.
    Assumes the first line contains the time step size.
    """
    time = np.loadtxt(inflow_file)[:,0]
    try:
        time_step = np.diff(time)[0]  # Get the first time step size
        return time_step
    except ValueError:
        print("Error: The first line of the inflow file does not contain a valid time step size.")
        return 0.001  # default value if parsing fails


def run_1d_simulation(solver_path, input_file_path, res_1D):
    # build path to your log file
    log_path = os.path.join(res_1D, 'log.txt')

    # open the log in append-mode (use 'w' if you want to overwrite each time)
    with open(log_path, 'a') as log_file:
        subprocess.run(
            [solver_path, input_file_path],
            cwd=res_1D,
            stdout=log_file,           # redirect stdout into the file
            stderr=subprocess.STDOUT,  # mix stderr into stdout (optional)
            shell=False
        )


def run_with_env(python_exe, solver_script, args, workdir, log_path=None):
    """
    Launch `solver_script` under the Python at `python_exe`, 
    ensuring we don’t inherit a broken PYTHONHOME/PYTHONPATH.
    Optionally redirect output into log_path.
    """
    # 1) Build a “clean” copy of the environment
    env = os.environ.copy()
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)

    # 2) Prepare the command
    cmd = [python_exe, solver_script] + args

    # 3) Choose where to send stdout/stderr
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        logf = open(log_path, 'a')
        stdout = logf
        stderr = subprocess.STDOUT
    else:
        stdout = None
        stderr = None

    # 4) Run it
    result = subprocess.run(
        cmd,
        cwd=workdir,
        env=env,
        stdout=stdout,
        stderr=stderr,
        shell=False
    )

    if log_path:
        logf.close()

    return result.returncode


def create_and_run_zerod_simulation(py_bin, py_filename, input_file_path, res_0D):
    import os
    # ensure output dir exists
    os.makedirs(res_0D, exist_ok=True)

    script_path = os.path.join(res_0D, py_filename)
    log_path    = os.path.join(res_0D, 'zerod.log')

    # write your one-off script
    write_text(script_path,    'import pysvzerod\n', 'w')
    write_text(script_path,   'solver = pysvzerod.Solver("{0}")\n'.format(input_file_path), 'a')
    write_text(script_path,   'solver.run()\n', 'a')

    print("→ Launching 0D simulation with:", py_bin, script_path)
    ret = run_with_env(py_bin, script_path, [], res_0D, log_path)

    if ret != 0:
        print(" 0D solver exited with code", ret, "— see log:", log_path)
    else:
        print("0D solver finished successfully (log at", log_path, ")")

def write_template_config(path,order):
    """
    Writes out an INI-style template config file at `path`.
    Users can open and edit this, changing values as needed.
    """
    cfg = configparser.ConfigParser()

    # Section for your 1D sim parameters
    cfg['Simulation'] = {
        'number_of_cycles':            '15',
        'model_order':                 str(order),  # 1 for 1D, 0 for 0D
        'element_size':                '0.01',
        'time_step_size':              'auto',     # 'auto' to compute from inflow file
        'num_time_steps_per_cycles':   'auto',     # 'auto' to compute from file+cycles
        'save_data_freq':              '1',
    }

    # Section for physical constants
    cfg['Physics'] = {
        'density':                  '1.06',
        'viscosity':                '0.04',
        'olufsen_material_k1':      '0.0',
        'olufsen_material_k2':      '-22.5267',
        'olufsen_material_k3':      '1.0e7',
        'olufsen_exponent':         '1.0',
        'olufsen_pressure':         '0.0',
        'linear_material_ehr':      '1e7',
        'linear_material_pressure': '0.0',
    }

    with open(path, 'w') as f:
        f.write("# This is your simulation config. Edit values as needed.\n")
        f.write("# time_step_size and num_time_steps_per_cycles are automatically computed from your inflow_1D.flow file.\n")
        f.write("# Recommend leaving it as auto.\n")
        cfg.write(f)
    print("Template config written to {}".format(path))


def load_config(path, inflow_file_path):
    """
    Reads the INI file at `path` and returns a populated Parameters() object.
    Uses `inflow_file_path` when 'auto' is selected.
    """
    if not os.path.exists(path):
        raise IOError("Config file not found: {}".format(path))

    cfg = configparser.ConfigParser()
    cfg.read(path)

    sim  = cfg['Simulation']
    phys = cfg['Physics']

    P = Parameters()
    P.model_order    = sim.getint('model_order')
    P.element_size   = sim.getfloat('element_size')
    P.save_data_freq = sim.getint('save_data_freq')

    # --- time step size ---
    tcfg = sim.get('time_step_size', 'auto')
    if tcfg == 'auto':
        P.time_step = get_timestep_size(inflow_file_path)
    else:
        # explicit float
        P.time_step = float(tcfg)
        print("You set time_step_size explicitly to {}. Make sure it matches {}"
              .format(P.time_step, inflow_file_path))

    # --- number of timesteps ---
    ncfg = sim.get('num_time_steps_per_cycles', 'auto')
    if ncfg == 'auto':
        cycles = sim.getint('number_of_cycles')
        P.num_time_steps = get_number_of_timesteps(cycles, inflow_file_path)
    else:
        P.num_time_steps = int(ncfg)
        print("You set num_time_steps_per_cycles explicitly to {}. "
              .format(P.num_time_steps) +
              "Make sure it matches cycles and inflow file.")

    # physical params
    P.density                   = phys.getfloat('density')
    P.viscosity                 = phys.getfloat('viscosity')
    P.olufsen_material_k1       = phys.getfloat('olufsen_material_k1')
    P.olufsen_material_k2       = phys.getfloat('olufsen_material_k2')
    P.olufsen_material_k3       = phys.getfloat('olufsen_material_k3')
    P.olufsen_material_exponent = phys.getfloat('olufsen_exponent')
    P.olufsen_material_pressure = phys.getfloat('olufsen_pressure')
    P.linear_material_ehr       = phys.getfloat('linear_material_ehr')
    P.linear_material_pressure  = phys.getfloat('linear_material_pressure')

    return P
