"""
init functions
"""
import os



### define all neccessary paths

Windows = True # are we running on Windows?
OneDSolv = "c:/Program Files/SimVascular/svOneDSolver/2022-10-04/svOneDSolver.exe"
zerod_python_bin = 'C:/Users/bygan/anaconda3/envs/MIROS/python.exe'
local_py_bin = 'C:/Users/bygan/anaconda3/envs/MIROS/python.exe' # activate your env , and 'where python'

#  for linux or macOS
sv_py_bin = None # '/usr/local/sv/simvascular/2025-06-21/simvascular'

# for windows
if Windows == True:
    sv_dir = 'C:/Program Files/SimVascular/SimVascular/2023-03-27' #
    sv_bat = 'sv.bat' # no need to change
else:
    sv_dir, sv_bat = None, None 


# folder to save results
master_folder = "c:/Users/bygan/Documents/MIROS/test_windows"

# used in post_process_seqseg.py
segseqed_model = "c:/Users/bygan/Documents/MIROS/0176_surface_mesh_smooth_182_steps.vtp"
seqseg_cl = 'c:/Users/bygan/Documents/MIROS/0176_centerline_182_steps.vtp'
clipped_seqseg_results =  os.path.join(master_folder, 'clipped131.vtp') # os.path.join(master_folder, 'clipped_seqseg_results')








bc_filename = 'rcrt.dat' # name of the boundary condition template file to be created

res_folder_1D = os.path.join(master_folder, '1D_results')
res_folder_0D = os.path.join(master_folder, '0D_results')

### assumptions
# edge length range for remeshing 
edge_min = 0.1
edge_max = 0.1

caps_folder = os.path.join(master_folder, 'caps_and_wall')
inflow_file_path = os.path.join(master_folder, 'inflow_1d.flow')

__all__ = ['OneDSolv', 'zerod_python_bin', 'segseqed_model', 'master_folder', 'local_py_bin', 'sv_py_bin',
           'bc_filename', 'res_folder_1D', 'res_folder_0D',
           'edge_min', 'edge_max', 'caps_folder', 'inflow_file_path', 'seqseg_cl', 'Windows', 'sv_dir', 'sv_bat',
           'clipped_seqseg_results',
           ]

