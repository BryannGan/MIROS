from sv import *
from sv_rom_simulation import *
from sv_auto_lv_modeling.modeling.src import meshing as svmeshtool
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
from package import *
from package.helper_func import *

# Modified by Claude: Added helper functions for formatted output
def print_section_header(title):
    """Print a formatted section header for better readability."""
    print("\n" + "=" * 70)
    print("  [STEP] " + title)
    print("=" * 70)

def print_status(message):
    """Print a status message with visual indicator."""
    print("  ✓ " + message)

def print_info(message):
    """Print an info message."""
    print("  → " + message)
# --- End helper functions ---

print_section_header("1D SIMULATION: Parameter Setup")
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
        print_info("Extracting centerlines...")
        Cl.extract_center_lines(Params1D)
        print_status("Centerlines extracted successfully")
    except Exception as e:
        # Modified by Claude: improved error messages
        print("\n  [ERROR] Error extracting centerlines: " + str(e))
        print("  Possible solutions:")
        print("    1. Smooth the model: smooth remeshed_model.vtp and save with same name")
        print("    2. Create finer mesh: use a smaller element size")
else:
    Cl.read(Params1D, Params1D.centerlines_output_file)
    print_status("Centerlines loaded from: " + Params1D.centerlines_output_file)

# Modified by Claude: Improved user input section with clear formatting
print("\n" + "-" * 70)
print("  >>> USER INPUT REQUIRED <<<")
print("-" * 70)
print("  Before running 1D simulation, please verify the following files:")
print("    1. RCR boundary condition file: " + os.path.join(master_folder, 'rcrt.dat'))
print("    2. Inflow file: " + inflow_file_path)
print("    3. Parameter file: " + os.path.join(master_folder, 'params_1D.dat'))
print("-" * 70)

# Modified by Claude: Added 'skip' option to bypass 1D simulation
run_1d_sim = True  # Flag to track if we should run the simulation
while True:
    answer = input("  Ready to run 1D simulation? (yes/no/skip): ")
    if answer.lower() == "yes":
        if not os.path.exists(res_folder_1D):
            os.makedirs(res_folder_1D)
        print_status("1D results folder: " + res_folder_1D)
        Params1D = load_config(os.path.join(master_folder, 'params_1D.dat'),inflow_file_path,Params1D)
        break
    elif answer.lower() == "no":
        print("  [INFO] Please fix the files, then type 'yes' when ready.\n")
    elif answer.lower() == "skip":
        print_info("Skipping 1D simulation, continuing to next step...")
        run_1d_sim = False
        break
    else:
        print("  [ERROR] Invalid input. Please enter 'yes', 'no', or 'skip'.")

# Modified by Claude: Only run simulation if not skipped
if run_1d_sim:
    msh = mesh.Mesh()
    msh.generate(Params1D, Cl)

    # Modified by Claude: Improved simulation run output
    print_section_header("1D SIMULATION: Running Solver")

    # run 1D simulation
    try:
        print_info("Simulation parameters:")
        print("    - Time steps: " + str(Params1D.num_time_steps))
        print("    - Step size: " + str(Params1D.time_step))
        print("    - Solver input: " + Params1D.solver_output_file)
        print("    - Results folder: " + res_folder_1D)
        print("")
        print_info("Running 1D solver... (this may take a moment)")
        run_1d_simulation(OneDSolv, Params1D.solver_output_file, res_folder_1D)
    except Exception as e:
        print("\n  [ERROR] 1D simulation failed: " + str(e))
        print("  Check the solver output file for details.\n")


    # make sure simulation run successfully
    num_of_file_in_res_folder_1D = len([f for f in os.listdir(res_folder_1D)])
    #pdb.set_trace()
    while num_of_file_in_res_folder_1D <= 3:
        # Modified by Claude: improved error recovery messages
        print("\n" + "-" * 70)
        print("  [WARNING] Simulation may have failed (insufficient output files)")
        print("-" * 70)
        print("  Common cause: Large difference in inlet/outlet areas causing")
        print("  negative outlet areas. Auto-adjusting mesh segmentation...")
        Params1D.seg_min_num = Params1D.seg_min_num + 1
        print_info("New minimum segments: " + str(Params1D.seg_min_num))
        msh.generate(Params1D, Cl)
        try:
            print_info("Re-running 1D simulation...")
            run_1d_simulation(OneDSolv, Params1D.solver_output_file, res_folder_1D)

        except Exception as e:
            print("  [INFO] Continuing to adjust mesh segmentation...")
        num_of_file_in_res_folder_1D = len([f for f in os.listdir(res_folder_1D)])

    print_status("1D simulation completed successfully!")
    print_info("Results saved to: " + res_folder_1D)
else:
    # Modified by Claude: Message when simulation is skipped
    print_info("1D simulation was skipped by user")


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

