# MIROS - Project Context

## Overview
**MIROS** (Medical Image to Patient-Specific Reduced-Order Hemodynamic Model Simulation in Minutes) is a Python pipeline that converts medical imaging data into patient-specific blood flow simulations using SimVascular.

## Architecture

### Entry Point
```bash
python -m package
```

### Core Modules (`package/`)

| Module | Purpose |
|--------|---------|
| `__init__.py` | Configuration: paths, solvers, OS detection, mesh params, BC tuning params |
| `__main__.py` | Main orchestrator with 4 execution modes |
| `sv_preprocess.py` | Surface remeshing, volume mesh gen, boundary extraction |
| `gen_inflow.py` | Interactive GUI for cardiac inflow waveform design |
| `tune_bc.py` | **NEW**: Automatic RCR boundary condition optimization |
| `gen_params_cl_run_1D.py` | 1D simulation setup (centerlines, mesh, OneDSolver) |
| `gen_params0D.py` | 0D simulation setup |
| `run_0D.py` | 0D solver execution via pysvzerod |
| `extract_1d_res.py` | 1D result extraction (CSV, VTP, VTU) |
| `extract_0d_res.py` | 0D result extraction and statistics |
| `helper_func.py` | Shared utilities (mesh ops, config, solver execution) |
| `post_process_seqseg.py` | Optional automatic outlet clipping |

## Workflow Pipeline

### Run Modes (select at startup)
- **[1] Full workflow with manual BC**: User provides rcrt.dat file
- **[2] Full workflow with automatic BC tuning**: Optimize BCs from targets (NEW)
- **[3] Extract 1D results only**: Skip to 1D result extraction
- **[4] Extract 0D results only**: Skip to 0D result extraction

### Full Workflow Steps
1. **Input**: `clipped_seqseg_results.vtp` (surface mesh from SeqSeg)
2. **Preprocess**: Remesh surface → volume mesh → extract boundaries
3. **Inflow Design**: Design cardiac flow waveform via interactive GUI
4. **Boundary Conditions**:
   - Mode 1: Edit `rcrt.dat` manually
   - Mode 2: Automatic tuning from flow splits + target pressures
5. **0D Sim**: Run svZeroDSolver (fast validation of BCs)
6. **0D Extract**: Generate 0D results and statistics
7. **1D Sim**: Extract centerlines → run OneDSolver
8. **1D Extract**: Generate CSV, VTP, VTU outputs

**Note**: 0D runs before 1D because BC tuning uses 0D for optimization, and 0D is fast for validating BCs before the longer 1D run.

### Automatic BC Tuning (Mode 2)
User provides:
- Flow split ratios (e.g., 25:25:25:25 across 4 outlets)
- Reference outlet for pressure targeting
- Target pressures: systolic (max), diastolic (min), mean in mmHg

System optimizes RCR parameters using fast 0D solver iterations.

## Key Files

| File | Description |
|------|-------------|
| `rcrt.dat` | RCR boundary conditions (user-edited) |
| `inflow_1d.flow` | Cardiac inflow waveform |
| `params_1D.dat` / `params_0D.dat` | Solver parameters |
| `extracted_centerlines.vtp` | Vessel centerlines |
| `1D_results/` | Flow, pressure, area results |
| `0D_results/` | Lumped-parameter results |

## Dependencies

- **SimVascular 2025-06-21+** with OneDSolver and svZeroDSolver
  - SimVascular Python packages: `/usr/local/sv/simvascular/2025-06-21/Python3.11/site-packages`
  - Key packages: `sv_rom_simulation`, `sv_auto_lv_modeling`
- **Python**: numpy, scipy, pandas, matplotlib, vtk, pyvista
- **SimVascular Python**: sv, sv_rom_simulation, sv_auto_lv_modeling, pysvzerod

## Platform Support
- **Windows**: Uses `sv.bat` wrapper
- **Linux/macOS**: Direct SimVascular Python binary

## Test Data
- `test_windows/` - Windows test files
- `test_Linux_Mac/` - Linux/macOS test files

## Key Technical Details
- **1D Solver**: Solves 1D Navier-Stokes along vessel centerlines
- **0D Solver**: Lumped-parameter circuit model
- **Material Model**: Olufsen nonlinear elastic (vessel walls)
- **Boundary Conditions**: RCR (Windkessel) model at outlets
- **Adaptive Features**: Auto edge size, mesh refinement on failure
