# MIROS

**Medical Image to Patient-Specific Reduced-Order Hemodynamic Model Simulation in Minutes**

We present a streamlined process to produce reduced-order model (ROM) simulations of patient-specific hemodynamics directly from volumetric angiography. Our framework integrates recent lumped-parameter and 1D Navier–Stokes solvers in the open-source SimVascular software with recent machine learning based segmentation techniques of SeqSeg (DOI: 10.1007/s10439-024-03611-z). The result is a workflow that reduces the time and interaction needed to go from medical images to informative simulations of blood flow. Namely, patient-specific simulation results can be achieved in the order of minutes from medical image data and basic parameterizations. 

*(Manuscript in preparation)*

---

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Workflow Overview](#workflow-overview)
- [Input/Output Files](#inputoutput-files)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Features

- Automated pipeline from medical images to hemodynamic simulations
- 1D Navier-Stokes blood flow simulation along vessel centerlines
- 0D lumped-parameter simulations at vessel outlets
- Interactive GUI for cardiac inflow waveform design
- Automatic adaptive mesh generation
- Cross-platform support (Windows, Linux, macOS)
- Comprehensive result extraction and visualization
- Optional automatic outlet definition from SeqSeg output

---

## Prerequisites

Before installing MIROS, ensure you have the following software installed:

| Software | Purpose | Download |
|----------|---------|----------|
| **SimVascular** (2025-06-21+) | Cardiovascular modeling and meshing | [simvascular.github.io](https://simvascular.github.io/) |
| **svOneDSolver** | 1D hemodynamic solver | [SimTK Downloads](https://simtk.org/frs/index.php?group_id=188) |
| **Python 3.9+** | Runtime environment | [python.org](https://www.python.org/) |
| **Conda** (recommended) | Environment management | [anaconda.com](https://www.anaconda.com/) |

---

## Installation (~20 minutes)

### 1. Clone the Repository

```bash
git clone https://github.com/BryannGan/MIROS.git
cd MIROS
```

### 2. Create Python Environment

```bash
# Create a new conda environment
conda create -n MIROS python=3.11
conda activate MIROS
```

### 3. Install Python Dependencies

```bash
# Install SeqSeg (ML-based segmentation toolkit)
pip install seqseg

# Install 0D solver Python interface
pip install git+https://github.com/simvascular/svZeroDSolver.git

# Install other dependencies
pip install numpy scipy pandas matplotlib vtk
```

### 4. Install SimVascular and svOneDSolver

Follow the official installation guides:
- **SimVascular**: https://simvascular.github.io/documentation/installation.html
- **svOneDSolver**: https://simtk.org/frs/index.php?group_id=188

### 5. Configure MIROS

Edit `package/__init__.py` to set paths for your system. See the [Configuration](#configuration) section below for detailed instructions.

### 6. Verify Installation

```bash
conda activate MIROS
cd /path/to/MIROS
python -m package
```

---

## Configuration

All configuration is done in `package/__init__.py`. Below is a complete guide to each setting.

### Operating System

```python
Windows = False  # Set to True if running on Windows, False for Linux/macOS
```

### Solver Paths

#### Linux/macOS

```python
# Path to the 1D solver executable
OneDSolv = '/usr/local/sv/oneDSolver/2025-07-02/bin/OneDSolver'

# Path to SimVascular executable (Linux/Mac only)
sv_py_bin = '/usr/local/sv/simvascular/2025-06-21/simvascular'

# Path to your Python environment's python binary
# Find this by running: which python (with your env activated)
local_py_bin = '/home/username/miniconda3/envs/MIROS/bin/python'
```

#### Windows

```python
Windows = True

# Path to the 1D solver executable
OneDSolv = 'C:/Program Files/SimVascular/svOneDSolver/2022-10-04/svOneDSolver.exe'

# SimVascular installation directory
sv_dir = 'C:/Program Files/SimVascular/SimVascular/2023-03-27'
sv_bat = 'sv.bat'  # Do not change this

# Path to your Python environment's python binary
# Find this by running: where python (with your env activated)
local_py_bin = 'C:/Users/username/anaconda3/envs/MIROS/python.exe'
```

### Project Paths

```python
# Master folder: where all results will be saved
# This folder should contain your input surface mesh
master_folder = '/path/to/your/project/folder'

# Path to your clipped (outlet-defined) surface mesh
# This is the SeqSeg output after outlets have been defined
clipped_seqseg_results = os.path.join(master_folder, 'clipped_seqseg_results.vtp')

# Model name (used in solver input files, no critical functionality)
surf_name = 'my_surface'
```

### Automatic Outlet Definition (Optional)

If you want MIROS to automatically clip the SeqSeg output and define outlets:

```python
automatic_define_outlets = True  # Enable automatic clipping

# Path to raw SeqSeg surface mesh (before clipping)
segseqed_model = '/path/to/seqseg_surface_mesh.vtp'

# Path to SeqSeg extracted centerline
seqseg_cl = '/path/to/seqseg_centerline.vtp'
```

> **Warning**: Automatic clipping is experimental and may not work for all geometries. For best results, use SimVascular GUI to manually clip your model.

### Mesh Settings

```python
# Edge size for surface remeshing
# Options:
#   - 'auto' (RECOMMENDED): Automatically compute based on model geometry
#   - numeric value (e.g., 0.1): Fixed edge size in model units
#
# If using a numeric value:
#   - Model in mm: typical values 0.1 - 1.0
#   - Model in cm: typical values 0.01 - 0.1
edge_size = 'auto'
```

### Complete Configuration Example

#### Linux/macOS Example

```python
import os

# Operating System
Windows = False

# Solver paths
OneDSolv = '/usr/local/sv/oneDSolver/2025-07-02/bin/OneDSolver'
sv_py_bin = '/usr/local/sv/simvascular/2025-06-21/simvascular'
local_py_bin = '/home/user/miniconda3/envs/MIROS/bin/python'

# Ignore these for Linux/Mac
sv_dir, sv_bat = None, None

# Project paths
master_folder = '/home/user/projects/patient_001'
clipped_seqseg_results = os.path.join(master_folder, 'clipped_seqseg_results.vtp')
surf_name = 'patient_001_aorta'

# Automatic clipping (disabled - using pre-clipped model)
automatic_define_outlets = False
segseqed_model = ''
seqseg_cl = ''

# Mesh settings
edge_size = 'auto'
```

#### Windows Example

```python
import os

# Operating System
Windows = True

# Solver paths
OneDSolv = 'C:/Program Files/SimVascular/svOneDSolver/2022-10-04/svOneDSolver.exe'
sv_dir = 'C:/Program Files/SimVascular/SimVascular/2023-03-27'
sv_bat = 'sv.bat'
local_py_bin = 'C:/Users/user/anaconda3/envs/MIROS/python.exe'
sv_py_bin = None  # Not used on Windows

# Project paths
master_folder = 'C:/Users/user/projects/patient_001'
clipped_seqseg_results = os.path.join(master_folder, 'clipped_seqseg_results.vtp')
surf_name = 'patient_001_aorta'

# Automatic clipping (disabled)
automatic_define_outlets = False
segseqed_model = ''
seqseg_cl = ''

# Mesh settings
edge_size = 'auto'
```

---

## Usage

### Running MIROS

```bash
# Activate your environment
conda activate MIROS

# Navigate to MIROS directory
cd /path/to/MIROS

# Run the pipeline
python -m package
```

### Workflow Modes

MIROS offers three workflow modes:

| Mode | Description | Use Case |
|------|-------------|----------|
| **Mode 1** | Full pipeline | Fresh simulation from surface mesh |
| **Mode 2** | 1D extraction only | Re-extract results from existing 1D simulation |
| **Mode 3** | 0D extraction only | Re-extract results from existing 0D simulation |

You will be prompted to select a mode when running MIROS.

---

## Workflow Overview

### Mode 1: Full Pipeline

The complete workflow consists of the following steps:

#### Step 1: Preprocessing (`sv_preprocess.py`)
- Loads your clipped SeqSeg surface mesh
- Computes adaptive edge size (if set to 'auto')
- Remeshes the surface for simulation quality
- Generates volume mesh using TetGen
- Extracts boundary surfaces (caps and wall)
- Prompts you to select the inlet cap

#### Step 2: Boundary Conditions
After preprocessing, you must edit the generated `rcrt.dat` file in your master folder to define RCR boundary conditions for each outlet:

```
# Example rcrt.dat format
2                           # Number of outlets

cap_outlet1                 # Outlet name (must match cap file name)
2                           # Number of RCR parameters
Rp Rd                       # Proximal resistance, Distal resistance
C                           # Capacitance

cap_outlet2
2
Rp Rd
C
```

#### Step 3: Inflow Waveform (`gen_inflow.py`)
- Interactive GUI to design cardiac inflow waveform
- Drag control points to shape the waveform
- Enter heart rate and number of time steps
- Alternatively, use an existing inflow file

#### Step 4: 1D Simulation (`gen_params_cl_run_1D.py`)
- Generates parameter configuration file (`params_1D.dat`)
- Extracts centerlines from the model
- Creates 1D mesh
- Runs the OneDSolver
- Automatically retries with finer mesh if simulation fails

#### Step 5: 0D Simulation (`gen_params0D.py` + `run_0D.py`)
- Sets up 0D simulation parameters
- Runs svZeroDSolver
- Saves results to CSV

#### Step 6: Result Extraction
- **1D Results** (`extract_1d_res.py`): Extracts flow, pressure, and area waveforms; projects onto centerlines and volume mesh; generates CSV and VTP/VTU files
- **0D Results** (`extract_0d_res.py`): Analyzes outlet waveforms; computes statistics; generates plots

### Modes 2 & 3: Extraction Only

Use these modes to re-analyze existing simulation results without re-running the solvers.

---

## Input/Output Files

### Input Files

| File | Description | Location |
|------|-------------|----------|
| `clipped_seqseg_results.vtp` | Clipped surface mesh with defined outlets | `master_folder` |
| `seqseg_centerline.vtp` | SeqSeg centerline (if using auto-clipping) | User-specified |

### Generated Configuration Files

| File | Description | User Action |
|------|-------------|-------------|
| `rcrt.dat` | RCR boundary conditions | **Must edit** before simulation |
| `params_1D.dat` | 1D simulation parameters | Optional editing |
| `params_0D.dat` | 0D simulation parameters | Optional editing |
| `inflow_1d.flow` | Cardiac inflow waveform | Generated via GUI |

### Output Files

#### Mesh Files (in `master_folder`)
| File | Description |
|------|-------------|
| `remeshed_clipped_seqseg_results.vtp` | Remeshed surface mesh |
| `volume_mesh.vtu` | 3D tetrahedral volume mesh |

#### Boundary Surfaces (in `caps_and_wall/`)
| File | Description |
|------|-------------|
| `wall.vtp` | Vessel wall surface |
| `cap_*.vtp` | Individual cap surfaces for each outlet |
| `cap_areas.txt` | Computed area for each cap |

#### 1D Results (in `1D_results/`)
| File | Description |
|------|-------------|
| `*_flow.csv` | Flow waveforms at each segment |
| `*_pressure.csv` | Pressure waveforms at each segment |
| `*_area.csv` | Area waveforms at each segment |
| `centerline_results.vtp` | Centerline with projected results |
| `volume_results.vtu` | Volume mesh with projected results |

#### 0D Results (in `0D_results/`)
| File | Description |
|------|-------------|
| `0D_results.csv` | Raw 0D solver output |
| `outlet_statistics.csv` | Summary statistics for each outlet |
| `outlet_*.png` | Waveform plots for each outlet |

---

## Troubleshooting

### Common Issues

#### "SimVascular not found" or import errors

**Solution**: Verify your `sv_py_bin` path points to the correct SimVascular executable:
```bash
# Linux/Mac: Find SimVascular
ls /usr/local/sv/simvascular/

# Windows: Check Program Files
dir "C:\Program Files\SimVascular"
```

#### "OneDSolver not found"

**Solution**: Verify your `OneDSolv` path:
```bash
# Linux/Mac
ls /usr/local/sv/oneDSolver/

# Windows
dir "C:\Program Files\SimVascular\svOneDSolver"
```

#### 1D simulation fails with "Simulation crashed"

**Possible causes**:
1. **Mesh too coarse**: MIROS will automatically retry with finer mesh
2. **Invalid boundary conditions**: Check `rcrt.dat` for correct format and reasonable values
3. **Inflow waveform issues**: Ensure smooth waveform without discontinuities

#### "No caps found" error

**Solution**: Ensure your input mesh has properly defined outlets. The mesh should have distinct cap surfaces at each outlet.

#### Python environment issues

**Solution**: Ensure you're using the correct Python environment:
```bash
conda activate MIROS
which python  # Linux/Mac
where python  # Windows
```
Update `local_py_bin` in `__init__.py` with this path.

#### GUI not displaying (Linux)

**Solution**: Ensure you have a display configured:
```bash
# If using SSH, enable X11 forwarding
ssh -X user@host

# Or set display
export DISPLAY=:0
```

### Getting Help

If you encounter issues not covered here:
1. Check that all paths in `__init__.py` are correct
2. Verify all dependencies are installed
3. Open an issue on GitHub: https://github.com/BryannGan/MIROS/issues

---

## Citation

If you use MIROS in your research, please cite:

*(Citation information will be added upon manuscript publication)*

Related work:
- SeqSeg: DOI: 10.1007/s10439-024-03611-z
- SimVascular: https://simvascular.github.io/

---

## License

This project is licensed under the terms specified in the LICENSE file.

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
