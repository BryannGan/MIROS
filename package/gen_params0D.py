from sv import *
from sv_rom_simulation import *
from sv_auto_lv_modeling.modeling.src import meshing as svmeshtool
import os
from __init__ import *
from helper_func import *

# set up 1D parameters

write_template_config(os.path.join(master_folder, 'params_0D.dat'), 0)
Params1D = load_config(os.path.join(master_folder, 'params_0D.dat'),inflow_file_path)


# output directories
Params0D.output_directory = master_folder
Params0D.boundary_surfaces_dir = caps_folder
Params0D.inlet_face_input_file = 'inlet.vtp'
Params0D.centerlines_output_file = os.path.join(master_folder,'extracted_centerlines.vtp')
Params0D.surface_model = os.path.join(master_folder, 'remeshed_model.vtp')
Params0D.inflow_input_file = inflow_file_path
Params0D.solver_output_file = os.path.join(master_folder,'0D_solver_input.json')
Params0D.model_name = 'your_model_name'
Params0D.outflow_bc_type = 'rcr'
Params0D.uniform_bc = False
Params0D.seg_size_adaptive = False
Params0D.seg_min_num = 4
Params0D.outlet_face_names_file = os.path.join(master_folder,'centerlines_outlets.dat')
Params0D.outflow_bc_file = os.path.join(master_folder, 'rcrt.dat')

Cl = Centerlines()
if not os.path.exists(Params0D.centerlines_output_file):
    try:
        Cl.extract_center_lines(Params0D)
    except Exception as e:
        print("Error occurred while extracting centerlines: ", e)
        print('option 1: smooth the model; smooth remeshed_model.vtp and save it as the same name') # needs work
        print('option 2: create finer mesh; use a smaller element size above') # needs work
else:
    Cl.read(Params0D, Params0D.centerlines_output_file)

while True:
    answer = input(
        "Before running the 0D simulation, please check your RCR boundary "
        "condition file and inflow file, and make sure they are correct.\n"
        "Do you want to continue? (yes/no): "
    )
    if answer.lower() == "yes":
        if not os.path.exists(res_folder_0D):
            os.makedirs(res_folder_0D)
            print("0D results folder created and can be found at: ", res_folder_0D)
            print('\n'  )
        break
    elif answer.lower() == "no":
        print("Then go fix it.\n")
    else:
        print("Invalid input. Please enter 'yes' or 'no'.")

msh = mesh.Mesh()
msh.generate(Params0D, Cl)



# run0D = subprocess.run(
#     ['svzerodsolver',
#      os.path.join(master_folder, '0D_solver_input.json'),
#      os.path.join(res_folder_0D, '0D_results.csv')
#      ],
#     cwd=os.path.dirname(__file__),
#     text=True,
#     check=True
# )

# num_of_file_in_res_folder_0D = len([f for f in os.listdir(res_folder_0D) if f.endswith('.csv')])

# if num_of_file_in_res_folder_0D > 0:
#     print("0D simulation completed successfully.")
#     print("Results can be found at: ", res_folder_0D)
# else:
#     print("0D simulation failed. Please check the solver output file for more details.")
#     print("automatically increase the number of segments in the 0D model and rerun the simulation.")
#     while num_of_file_in_res_folder_0D == 0:
#         Params0D.seg_min_num += 1
#         print('New minimum number of segments: ', Params0D.seg_min_num)
#         msh.generate(Params0D, Cl)
#         run0D = subprocess.run(
#             ['svzerodsolver',
#             os.path.join(master_folder, '0D_solver_input.json'),
#             os.path.join(res_folder_0D, '0D_results.csv')
#             ],
#             cwd=os.path.dirname(__file__),
#             text=True,
#             check=True
#         )
#         num_of_file_in_res_folder_0D = len([f for f in os.listdir(res_folder_0D) if f.endswith('.csv')])

#     print("0D simulation completed successfully after adjusting the number of segments.")


