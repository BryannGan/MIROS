from sv import *
from sv_rom_simulation import *
from sv_auto_lv_modeling.modeling.src import meshing as svmeshtool
import os
from package import *
from helper_func import *



write_template_config(os.path.join(master_folder, 'params_1D.dat'), 1)

# output directories
Params1D = Parameters()
Params1D.output_directory = master_folder
Params1D.boundary_surfaces_dir = caps_folder
Params1D.inlet_face_input_file = 'inlet.vtp'
Params1D.centerlines_output_file = os.path.join(master_folder,'extracted_centerlines.vtp')
Params1D.surface_model = os.path.join(master_folder, 'remeshed_model.vtp')
Params1D.inflow_input_file = inflow_file_path
Params1D.solver_output_file = os.path.join(master_folder,'1D_solver_input.in')
Params1D.model_name = surf_name ## change this to your model name
Params1D.outflow_bc_type = 'rcr'
Params1D.uniform_bc = False
Params1D.seg_size_adaptive = True
Params1D.seg_min_num = 4
Params1D.outlet_face_names_file = os.path.join(master_folder,'centerlines_outlets.dat')
Params1D.outflow_bc_file = os.path.join(master_folder, 'rcrt.dat')

Cl = Centerlines()
if not os.path.exists(Params1D.centerlines_output_file):
    try:
        Cl.extract_center_lines(Params1D)
    except Exception as e:
        print("Error occurred while extracting centerlines: ", e)
        print('option 1: smooth the model; smooth remeshed_model.vtp and save it as the same name') # needs work
        print('option 2: create finer mesh; use a smaller element size above') # needs work
else:
    Cl.read(Params1D, Params1D.centerlines_output_file)

while True:
    answer = input(
        "Before running the 1D simulation, please check your RCR boundary "
        "condition file, inflow file, and parameter file, and make sure they are correct.\n"
        "Do you want to continue? (yes/no): "
    )
    if answer.lower() == "yes":
        if not os.path.exists(res_folder_1D):
            os.makedirs(res_folder_1D)
            print("1D results folder created and can be found at: ", res_folder_1D)
            print('\n'  )
            Params1D = load_config(os.path.join(master_folder, 'params_1D.dat'),inflow_file_path,Params1D)
        break
    elif answer.lower() == "no":
        print("Then go fix it.\n")
    else:
        print("Invalid input. Please enter 'yes' or 'no'.")

msh = mesh.Mesh()
msh.generate(Params1D, Cl)




# run 1D simulation
try:
    print('\n')
    print('Running 1D simulation...')
    print('number of time steps: ', Params1D.num_time_steps)
    print('time step size: ', Params1D.time_step)
    print('solver output file: ', Params1D.solver_output_file)
    print('results folder: ', res_folder_1D)
    run_1d_simulation(OneDSolv, Params1D.solver_output_file, res_folder_1D)
except Exception as e:
    print("An error occurred while running the 1D simulation: ", e)
    print("Please check the solver output file for more details.\n")


# make sure simulation run successfully
num_of_file_in_res_folder_1D = len([f for f in os.listdir(res_folder_1D)])
#pdb.set_trace()
while num_of_file_in_res_folder_1D <= 3:
    print('\n')
    print('A common error for 1D ROM, which can occur when there is a large difference in the inlet and outlet areas of a segment, is outlet areas going negative.')
    print('Splitting the vessels into smaller segments until we avoid this error.')
    Params1D.seg_min_num = Params1D.seg_min_num + 1
    print('New minimum number of segments: ', Params1D.seg_min_num)
    msh.generate(Params1D, Cl)
    try:
        print('Running 1D simulation')
        run_1d_simulation(OneDSolv, Params1D.solver_output_file, res_folder_1D)
        
    except Exception as e:
        print('Continuing to split the vessels until we avoid this error.')
    num_of_file_in_res_folder_1D = len([f for f in os.listdir(res_folder_1D)])


####### 0D ########


# # set up 0D parameters
# Params0D = Parameters()
# Params0D.model_order = 0
# Params0D.element_size = 0.01

# # physical parameters
# Params0D.density = 1.06
# Params0D.viscosity = 0.04
# Params0D.olufsen_material_k1 = 0.0
# Params0D.olufsen_material_k2 = -22.5267
# Params0D.olufsen_material_k3 = 1.0e7
# Params0D.olufsen_material_exponent = 1.0
# Params0D.olufsen_material_pressure = 0.0
# Params0D.linear_material_ehr = 1e7
# Params0D.linear_material_pressure = 0.0

# # output directories
# Params0D.output_directory = master_folder
# Params0D.boundary_surfaces_dir = caps_folder
# Params0D.inlet_face_input_file = 'inlet.vtp'
# Params0D.centerlines_output_file = os.path.join(master_folder,'extracted_centerlines.vtp')
# Params0D.surface_model = os.path.join(master_folder, 'remeshed_model.vtp')
# Params0D.inflow_input_file = inflow_file_path
# Params0D.solver_output_file = os.path.join(master_folder,'0D_solver_input.in')
# Params0D.model_name = 'your_model_name'
# Params0D.outflow_bc_type = 'rcr'
# Params0D.uniform_bc = False
# Params0D.seg_size_adaptive = True
# Params0D.seg_min_num = 4
# Params0D.outlet_face_names_file = os.path.join(master_folder,'centerlines_outlets.dat')
# Params0D.num_time_steps = 12000
# Params0D.outflow_bc_file = os.path.join(master_folder, 'rcrt.dat')

# Cl0D = Centerlines()
# if not os.path.exists(Params0D.centerlines_output_file):
#     try:
#         Cl0D.extract_center_lines(Params0D)
#     except Exception as e:
#         print("Error occurred while extracting centerlines: ", e)
#         print('option 1: smooth the model') # needs work
#         print('option 2: create finer mesh') # needs work

# else:
#     Cl0D.read(Params0D, Params0D.centerlines_output_file)
    
    

# while True:
#     answer = input(
#         "Before running the 0D simulation, please check your RCR boundary "
#         "condition file and inflow file, and make sure they are correct.\n"
#         "Do you want to continue? (yes/no): "
#     )
#     if answer.lower() == "yes":
#         if not os.path.exists(res_folder_0D):
#             os.makedirs(res_folder_0D)
#             print("0D results folder created and can be found at: ", res_folder_0D)
#         break
#     elif answer.lower() == "no":
#         print("Then go fix it.\n")
#     else:
#         print("Invalid input. Please enter 'yes' or 'no'.")

# msh0D = mesh.Mesh()
# msh0D.generate(Params0D, Cl0D)
# python_exe_file = os.path.join(master_folder, 'zerod_solver.py')

# try:
#     print('Running 0D simulation')
#     create_and_run_zerod_simulation(zerod_python_bin, python_exe_file, Params0D.solver_output_file, res_folder_0D)
# except Exception as e:
#     print("well")

