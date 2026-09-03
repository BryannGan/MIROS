# Vendored: sv_rom_simulation

Source: SimVascular 2025-06-21 release, `Python3.11/site-packages/sv_rom_simulation`
(https://github.com/SimVascular/SimVascular, `Python/site-packages/sv_rom_simulation`).

Copyright (c) Stanford University, The Regents of the University of California,
and others. All Rights Reserved. Distributed under the permissive license
reproduced at the top of every file in this directory.

Modifications by MIROS:
- `centerlines.py`: `sv_centerlines()` no longer imports the `sv` binary module
  (it raises with guidance); `Centerlines.from_polydata()` added so centerlines
  computed by `miros.geometry` can be passed in.
- `mesh.py`: the adaptive segmentation seeds `pwlf.PiecewiseLinFit(..., seed=0)`, so
  repeated runs of the same case produce the same 1D segments.
- No other functional changes. `io_0d.py`, `io_1d.py`, `parameters.py`, `models.py`,
  `utils.py`, `io_headers.py`, `manage.py`, `generate_1d_mesh.py` are verbatim.
