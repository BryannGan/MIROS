from sv import *
from sv_rom_simulation import *
from sv_auto_lv_modeling.modeling.src import meshing as svmeshtool
# from inflow_editor import * # we are running this in a subprocess
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

import warnings
import subprocess

# from . import *
# from .helper_func import *
from package import *
from helper_func import *
'''
to use this code
/usr/local/sv/simvascular/2023-03-27/simvascular --python -- /home/bg2881/Documents/MIROS/MIROS/package/main1D.py
'''


### here! model(clipped_seqseg_results) needs to have boundary clipped open

# create master folder if not exists
if not os.path.exists(master_folder):
    os.makedirs(master_folder)
print("Results folder created and can be found at: ", master_folder)
print('\n')


# read the model using sv built-in function
segseqed_vtp = read_surface(clipped_seqseg_results,'vtp',None)

# load the model into a sv modeler object
modeler = modeling.PolyData(segseqed_vtp)

# compute faces (only 1 being the wall)
modeler.compute_boundary_faces(90.0) 

# fill holes with ids
filled = vmtk.cap(segseqed_vtp)
modeler = modeling.PolyData(filled)

# remesh the model, ensure boundary mesh quality
model_vtp = svmeshtool.remesh_polydata(modeler.get_polydata(),edge_min,edge_max)
modeler = modeling.PolyData(model_vtp)
write_polydata(os.path.join(master_folder, 'remeshed_model.vtp'), modeler.get_polydata())
print("Remeshed model saved at: ", os.path.join(master_folder, 'remeshed_model.vtp'))
print('\n')

# create a folder and write out caps
caps_folder = os.path.join(master_folder, 'caps_and_wall')
if not os.path.exists(caps_folder):
    os.makedirs(caps_folder)
write_caps_and_wall(caps_folder, modeler)
print("Caps and wall written to: ", caps_folder)
print('\n')

# ask user to define inflow cap
print("Please define the inflow cap name from the list of caps written to: ", caps_folder)
print('\n')
get_inlet_cap_name(caps_folder)



# create rcr boundary condition template from caps
create_rcr_bc_template(caps_folder, os.path.join(master_folder, bc_filename))
print("RCR boundary condition template created at: ", os.path.join(master_folder, bc_filename))
print('\n')
print("Please edit the RCR boundary condition template file to set the values for each cap.")
print('\n')

# compute cap areas use vtk
helper_txt_path = write_helper_txt(master_folder, caps_folder)
print('To assist you with creating RCR boundary condition file, read the helper text in model_info.txt that includes information about the cap area')
print('\n')

