# Vendored: sv_rom_extract_results

Source: SimVascular 2025-06-21 release, `Python3.11/site-packages/sv_rom_extract_results`
(https://github.com/SimVascular/SimVascular, `Python/site-packages/sv_rom_extract_results`).

Copyright (c) Stanford University, The Regents of the University of California,
and others. All Rights Reserved. Distributed under the permissive license
reproduced at the top of every file in this directory.

Modifications by MIROS:
- `extract_results.py`: the "No segment options are set" warning tested `outlet_segments and all_segments`; changed to `or` so it only fires when neither is set.
