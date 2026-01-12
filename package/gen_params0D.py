import sys
from sv import *
from sv_rom_simulation import *
from sv_auto_lv_modeling.modeling.src import meshing as svmeshtool
import os
from __init__ import *

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

# set up 0D parameters
print_section_header("0D SIMULATION: Parameter Setup")
write_template_config(os.path.join(master_folder, 'params_0D.dat'), 0)

# output directories
Params0D = Parameters()
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
Params0D.model_order = 0

Cl = Centerlines()
if not os.path.exists(Params0D.centerlines_output_file):
    try:
        print_info("Extracting centerlines...")
        Cl.extract_center_lines(Params0D)
        print_status("Centerlines extracted successfully")
    except Exception as e:
        # Modified by Claude: improved error messages
        print("\n  [ERROR] Error extracting centerlines: " + str(e))
        print("  Possible solutions:")
        print("    1. Smooth the model: smooth remeshed_model.vtp and save with same name")
        print("    2. Create finer mesh: use a smaller element size")
else:
    Cl.read(Params0D, Params0D.centerlines_output_file)
    print_status("Centerlines loaded from: " + Params0D.centerlines_output_file)

# Modified by Claude: Improved user input section with clear formatting
print("\n" + "-" * 70)
print("  >>> USER INPUT REQUIRED <<<")
print("-" * 70)
print("  Before running 0D simulation, please verify the following files:")
print("    1. RCR boundary condition file: " + os.path.join(master_folder, 'rcrt.dat'))
print("    2. Inflow file: " + inflow_file_path)
print("    3. Parameter file: " + os.path.join(master_folder, 'params_0D.dat'))
print("-" * 70)

# Modified by Claude: Added 'skip' option to bypass 0D setup
run_0d_setup = True  # Flag to track if we should run the setup
while True:
    answer = input("  Ready to run 0D simulation? (yes/no/skip): ")
    if answer.lower() == "yes":
        if not os.path.exists(res_folder_0D):
            os.makedirs(res_folder_0D)
        print_status("0D results folder: " + res_folder_0D)
        Params0D = load_config(os.path.join(master_folder, 'params_0D.dat'),inflow_file_path,Params0D)
        break
    elif answer.lower() == "no":
        print("  [INFO] Please fix the files, then type 'yes' when ready.\n")
    elif answer.lower() == "skip":
        print_info("Skipping 0D setup, continuing to next step...")
        run_0d_setup = False
        break
    else:
        print("  [ERROR] Invalid input. Please enter 'yes', 'no', or 'skip'.")

# Modified by Claude: Only run setup if not skipped
if run_0d_setup:
    msh = mesh.Mesh()
    msh.generate(Params0D, Cl)

    # Modified by Claude: Added completion message
    print_status("0D mesh generated successfully")
    print_info("Solver input: " + Params0D.solver_output_file)
    print_info("Proceeding to run 0D solver...")
else:
    # Modified by Claude: Message when setup is skipped
    print_info("0D setup was skipped by user")

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


