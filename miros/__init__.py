"""
MIROS - Medical Image to Patient-Specific Reduced-Order Hemodynamic Model
Simulation in Minutes.

    miros init CASE --surface model.vtp --inflow inflow.flow
    miros run CASE

A case directory holds one case.yaml with every answer the pipeline needs.
`miros run` computes caps and centerlines, builds the 0D and 1D models,
tunes RCR boundary conditions to flow splits and pressure targets, runs
svZeroDSolver and svOneDSolver, and extracts last-cycle results. No
SimVascular installation is required; only the two solvers.
"""

__version__ = "0.2.0.dev0"
