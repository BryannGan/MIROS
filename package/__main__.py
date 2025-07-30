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

from package import *


# ========================================================================
# ============================ intialize  ================================
if Windows:
  project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
  env = os.environ.copy()
  prev = env.get('PYTHONPATH', '')
  env['PYTHONPATH'] = project_root + (os.pathsep + prev if prev else '')
else:
  pass

    

# ========================================================================
# ======================= post-process seqseg results  ===================

'''
This part automaticall clips and define outlet for the seqseg model.
However, dependes on your model complexity,
instead of using this code which replies on a non-robust extracted centerline, 
you may use SimVascular to clip the caps open tailering to your needs.
If so, comment this out
'''

subprocess.run(
    [local_py_bin, 'post_process_seqseg.py'],
    cwd=os.path.dirname(__file__),  
    text=True,
    check=True
)

'''
notes: 
outputs the clipped seqseg model to master_folder's <clipped_seqseg_results> path, and clipping boxes
'''
# =======================================================================
# ============================ pre-process ==============================


if Windows:
    # copy your current environment, but prepend project_root to PYTHONPATH
    script = os.path.join(os.path.dirname(__file__), 'sv_preprocess.py') 
    #pdb.set_trace()
    # run bat via shell, but with PYTHONPATH set
    subprocess.run(
        f'"{sv_bat}" --python -- "{script}"',
        cwd=sv_dir,
        shell=True,
        check=True,
        text=True,
        env=env,
    )

else:
  preprocess = subprocess.run(
      [ sv_py_bin, 
        "--python",  # split flags out
        "--",
        "sv_preprocess.py"
      ],
      cwd=os.path.dirname(__file__),
      text=True,
      check=True
  )

# =======================================================================
# =======================================================================

get_inflow = subprocess.run(
    [local_py_bin, 'gen_inflow.py'],
    cwd=os.path.dirname(__file__),
    text=True,
    check=True
)   
# =======================================================================
# =======================================================================



if Windows:
    # copy your current environment, but prepend project_root to PYTHONPATH
    script = os.path.join(os.path.dirname(__file__), 'gen_params_cl_run_1D.py') 
    #pdb.set_trace()
    # run bat via shell, but with PYTHONPATH set
    subprocess.run(
        f'"{sv_bat}" --python -- "{script}"',
        cwd=sv_dir,
        shell=True,
        check=True,
        text=True,
        env=env,
    )
else:
    # run the 1D solver with the generated parameters
  gen_params_and_run1D = subprocess.run(
      [ sv_py_bin, 
        "--python",  # split flags out
        "--",
        "gen_params_cl_run_1D.py"
      ],
      cwd=os.path.dirname(__file__),
      text=True,
      check=True
  )
# =======================================================================
# =======================================================================

gen_params0D = subprocess.run(
    [ sv_py_bin, 
      "--python",  # split flags out
      "--",
      "gen_params0D.py"
    ],
    cwd=os.path.dirname(__file__),
    text=True,
    check=True
)
# =======================================================================
# =======================================================================
run_0D = subprocess.run(
    [local_py_bin, 'run_0D.py'],
    cwd=os.path.dirname(__file__),
    text=True,
    check=True
)



# # # ##add error handling for # of segments
# # # # run0D = subprocess.run(
# # # #     ['svzerodsolver',
# # # #      os.path.join(master_folder, '0D_solver_input.json'),
# # # #      os.path.join(res_folder_0D, '0D_results.csv')
# # # #      ],
# # # #     cwd=os.path.dirname(__file__),
# # # #     text=True,
# # # #     check=True
# # # # )
# # # # =======================================================================
# # # # =======================================================================

