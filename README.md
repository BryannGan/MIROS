# MIROS

**Medical Image to Patient-Specific Reduced-Order Hemodynamic Model Simulation in Minutes**

We present a streamlined process to produce reduced-order model (ROM) simulations of patient-specific hemodynamics directly from volumetric angiography. Our framework integrates recent lumped-parameter and 1D Navier–Stokes solvers in the open-source SimVascular software with recent machine learning based segmentation techniques of SeqSeg (DOI: 10.1007/s10439-024-03611-z). The result is a workflow that reduces the time and interaction needed to go from medical images to informative simulations of blood flow. Namely, patient-specific simulation results can be achieved in the order of minutes from medical image data and basic parameterizations.
*(Manuscript in preparation)*

---

## 📦 Installation

1. **Clone the repository**  
   ```bash
   git clone https://github.com/BryannGan/MIROS.git
   cd MIROS
   ```

3. **Install Nesscary Packages**
   ```bash
   # create your python env. eg via conda
   conda create -n MIROS python=3.11
   conda activate MIROS
   ```
   ```bash
   # install seqseg (toollkit to compute simulation ready surface model from medical image)
   pip install seqseg
   ```
   ```bash
   # install 0D solver. See (https://simvascular.github.io/documentation/rom_simulation.html#0d-solver-install)
   pip install git+https://github.com/simvascular/svZeroDSolver.git
   ```
   
   Install simvascular and svZeroDsolver(exe) according to instruction listed in https://simvascular.github.io/ and https://simtk.org/frs/index.php?group_id=188

5. **Change paths in __init__.py**
   Update the path to your computer configuration, such as the following
   ```bash
   OneDSolv = "c:/Program Files/SimVascular/svOneDSolver/2022-10-04/svOneDSolver.exe"
   zerod_python_bin = 'C:/Users/bygan/anaconda3/envs/MIROS/python.exe'
   local_py_bin = 'C:/Users/bygan/anaconda3/envs/MIROS/python.exe' # activate your env , and 'where python'
   ```

7. **Running the code**
   ```bash
    #activate your env
    cd <path_to_MIROS>
    python -m package #running the code
   ```
8. **Follow command line guidance to complete simulation**
+ Choose to automatically clip the SeqSeg result surface to define outlets.
+ Remesh model and create boundary condition template for users to edit
+ Generate inflow file via GUI
+ Create Parameter config file for user to edit
+ Run 1D simulation
+ Run 0D simulation
   
