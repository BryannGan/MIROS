# SimVascular reference for the validation tests

Generated with SimVascular 2025-06-21 (`sv.vmtk.centerlines`) from the same
surface. `tests/integration/test_centerlines_vs_simvascular.py` gates the
builtin centerline backend against these files:

- `extracted_centerlines.vtp` — SimVascular centerlines (columns of
  `CenterlineId` follow `centerlines_outlets.dat`, which in this old run was
  *not* consistent with the cap names; the tests map columns to caps by
  endpoint geometry, so it does not matter here)
- `0D_solver_input.json` — the 0D model SimVascular's ROM builder produced
- `rcrt.dat`, `caps.json` — boundary conditions and cap centroids/areas
  used to compare the two models with identical RCRs on the same outlets
