"""
init functions
"""
import os



### define all neccessary paths###

# OS
Windows = True # are we running on Windows?
# path to the 1D solver executable
OneDSolv = "c:/Program Files/SimVascular/svOneDSolver/2022-10-04/svOneDSolver.exe"
# path to the python bin in your environment
local_py_bin = 'C:/Users/bygan/anaconda3/envs/MIROS/python.exe' # activate your env , and 'where python'


# path to the SimVascular python bin
if Windows == True:
    sv_dir = 'C:/Program Files/SimVascular/SimVascular/2023-03-27' # change
    sv_bat = 'sv.bat' # DO NOT CHANGE
    
else:
    sv_dir, sv_bat = None, None

# for Linux and Ubuntu, set this one to your SimVascular python bin
sv_py_bin = None # '/usr/local/sv/simvascular/2025-06-21/simvascular'


# folder to save results
master_folder = "c:/Users/bygan/Documents/MIROS/test_windows"
clipped_seqseg_results = os.path.join(master_folder, 'clipped_seqseg_results.vtp') # do not change
surf_name = 'my_surface' # name of the model, used in the solver input file

# used in post_process_seqseg.py
# load the path to your seqseged generated model and centerlines - will optimize in later versions to automatically find these
segseqed_model = "c:/Users/bygan/Documents/MIROS/0176_surface_mesh_smooth_182_steps.vtp"
seqseg_cl = 'c:/Users/bygan/Documents/MIROS/0176_centerline_182_steps.vtp'


# edge length range for remeshing (depends on units)
edge_min = 0.1
edge_max = 0.1


# We recommend you DO NOT CHANGE the following
bc_filename = 'rcrt.dat' 
res_folder_1D = os.path.join(master_folder, '1D_results')
res_folder_0D = os.path.join(master_folder, '0D_results')

caps_folder = os.path.join(master_folder, 'caps_and_wall')
inflow_file_path = os.path.join(master_folder, 'inflow_1d.flow')

__all__ = ['OneDSolv', 'segseqed_model', 'master_folder', 'local_py_bin', 'sv_py_bin',
           'bc_filename', 'res_folder_1D', 'res_folder_0D',
           'edge_min', 'edge_max', 'caps_folder', 'inflow_file_path', 'seqseg_cl', 'Windows', 'sv_dir', 'sv_bat',
           'clipped_seqseg_results','surf_name'
           ]

