"""
init functions
"""
import os



### define all neccessary paths###

# OS
Windows = False # are we running on Windows?
# path to the 1D solver executable
OneDSolv = '/usr/local/sv/oneDSolver/2025-07-02/bin/OneDSolver' # "c:/Program Files/SimVascular/svOneDSolver/2022-10-04/svOneDSolver.exe"
# path to the python bin in your environment
local_py_bin = '/home/bg2881/miniconda3/envs/LA_main/bin/python' # 'C:/Users/bygan/anaconda3/envs/MIROS/python.exe' # activate your env , and 'where python'


# path to the SimVascular python bin
if Windows == True:
    sv_dir = 'C:/Program Files/SimVascular/SimVascular/2023-03-27' # change
    sv_bat = 'sv.bat' # DO NOT CHANGE
    
else:
    sv_dir, sv_bat = None, None # ignore this if not Windows

# for Linux and Ubuntu, set this one to your SimVascular python bin
sv_py_bin = '/usr/local/sv/simvascular/2025-06-21/simvascular'


# path to where you want to save results
master_folder = '/home/bg2881/Documents/MIROS/test_Linux_Mac' # "c:/Users/bygan/Documents/MIROS/test_windows"
clipped_seqseg_results = os.path.join(master_folder, 'clipped_seqseg_results.vtp') # locate your clipped (outlet defined) surface mesh here, in my case, it is in the master_folder
surf_name = 'my_surface' # name of the model, used in the solver input file, no critical functionality


# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# If you want the computer to clip (define outlets) for you, you can set the following two variables (used in post_process_seqseg.py)
# however, WARNING: this method is not robust, and may fail to clip the model properly
# we recommend you to use SimVascular GUI to clip the model tailering to your needs

automatic_define_outlets = False # if True, the code will use the following to clip the model and define outlets automatically
segseqed_model = "/home/bg2881/Documents/MIROS/0176_surface_mesh_smooth_182_steps.vtp" # path to your seqseg model (before clipping)
seqseg_cl = '/home/bg2881/Documents/MIROS/0176_centerline_182_steps.vtp'# path to your seqseg extracted centerline
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


# edge length range for remeshing (depends on units)
edge_min = 0.1
edge_max = 0.1


# DO NOT r change the following, unless you are changing the workflow or developing new features
bc_filename = 'rcrt.dat' 
res_folder_1D = os.path.join(master_folder, '1D_results')
res_folder_0D = os.path.join(master_folder, '0D_results')
caps_folder = os.path.join(master_folder, 'caps_and_wall')
inflow_file_path = os.path.join(master_folder, 'inflow_1d.flow')




__all__ = ['OneDSolv', 'segseqed_model', 'master_folder', 'local_py_bin', 'sv_py_bin',
           'bc_filename', 'res_folder_1D', 'res_folder_0D',
           'edge_min', 'edge_max', 'caps_folder', 'inflow_file_path', 'seqseg_cl', 'Windows', 'sv_dir', 'sv_bat',
           'clipped_seqseg_results','surf_name', 'automatic_define_outlets'
           ]

