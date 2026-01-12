import os
from __init__ import *
import pysvzerod
import pdb
import pandas as pd

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

print_section_header("0D SIMULATION: Running Solver")
print_info("Input file: " + os.path.join(master_folder, '0D_solver_input.json'))
print_info("Running 0D solver... (this may take a moment)")

solver = pysvzerod.Solver(os.path.join(master_folder, '0D_solver_input.json'))
try:
    solver.run()
    data = solver.get_full_result()
    df = pd.DataFrame(data)
    df.to_csv(os.path.join(res_folder_0D, '0D_results.csv'))
    # Modified by Claude: Added success message
    print_status("0D simulation completed successfully!")
    print_info("Results saved to: " + os.path.join(res_folder_0D, '0D_results.csv'))

    # Final summary
    print("\n" + "=" * 70)
    print("  [COMPLETE] MIROS Workflow Finished")
    print("=" * 70)
    print("  All simulations completed. Results (if ran) can be found at:")
    print("    - 1D results: " + res_folder_1D)
    print("    - 0D results: " + res_folder_0D)
    print("=" * 70 + "\n")

except Exception as e:
    # Modified by Claude: improved error messages
    print("\n  [ERROR] 0D simulation failed: " + str(e))
    print("-" * 70)
    print("  Troubleshooting:")
    print("    1. Ensure pysvzerod is correctly installed")
    print("    2. Check that the input file is properly formatted")
    print("    3. Review mesh geometry and boundary conditions")
    print("-" * 70)