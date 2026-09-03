# Vendored: sv_rom_extract_results

Source: SimVascular 2025-06-21 release, `Python3.11/site-packages/sv_rom_extract_results`
(https://github.com/SimVascular/SimVascular, `Python/site-packages/sv_rom_extract_results`).

Copyright (c) Stanford University, The Regents of the University of California,
and others. All Rights Reserved. Distributed under the permissive license
reproduced at the top of every file in this directory.

Modifications by MIROS:
- `extract_results.py`: the "No segment options are set" warning tested `outlet_segments and all_segments`; changed to `or` so it only fires when neither is set.
- `post.py`: `project_results_to_centerline()` removes the blanked branch id -1 only when
  it is present, so a model with no bifurcation can be extracted.
- `manage.py`: `init_logging()` closes and drops an earlier file handler instead of
  stacking a new one on every extraction (Windows could not delete `results/1D`).
