import os
from __init__ import *
import pysvzerod
import pdb
import pandas as pd

solver = pysvzerod.Solver(os.path.join(master_folder, '0D_solver_input.json'))

solver.run()
data = solver.get_full_results()
df = pd.DataFrame(data)
df.to_csv(os.path.join(res_folder_0D, '0D_results.csv'))