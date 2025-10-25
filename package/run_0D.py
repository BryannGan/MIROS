import os
from __init__ import *
import pysvzerod
import pdb
import pandas as pd

solver = pysvzerod.Solver(os.path.join(master_folder, '0D_solver_input.json'))
try: 
    solver.run()
    data = solver.get_full_result()
    df = pd.DataFrame(data)
    df.to_csv(os.path.join(res_folder_0D, '0D_results.csv'))
except Exception as e:
    print("Error occurred while running 0D solver: ", e)
    print("Please ensure that the 0D solver is correctly installed and the input file is properly formatted.")
    print("In addition, check solver output for more details regarding your mesh geometry and boundary conditions.")