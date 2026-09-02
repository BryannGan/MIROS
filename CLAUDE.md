# MIROS - Project Context

**MIROS** turns a vessel surface (SeqSeg output, clipped open) into patient-specific 0D and 1D
hemodynamic simulations. Standalone: no SimVascular installation; only `pysvzerod` (pip from git)
and the `svOneDSolver` executable are external. One code path for Linux / macOS / Windows.

## Entry points

```bash
miros doctor                       # packages + OneDSolver discovery
miros init DIR --surface S --inflow F
miros run DIR [--from STAGE] [--until STAGE] [--force]
miros status DIR
miros show caps DIR / miros inflow edit DIR   # need a display
python -m miros ...                # same thing without the console script
```

Dev env on this machine: conda `MIROS` (`/home/bg2881/miniconda3/envs/MIROS`), package installed
editable (`pip install -e .`). OneDSolver at `/usr/local/sv/oneDSolver/2025-07-02/bin/OneDSolver`.

## Layout

| Path | Purpose |
|---|---|
| `miros/config.py` | `case.yaml` schema (dataclasses), strict loader with type coercion, template |
| `miros/case.py`, `miros/manifest.py` | case directory, stage runner, content-hash manifest (`.miros/manifest.json`) |
| `miros/stages/*.py` | one module per stage: `inputs(case)`, `outputs(case)`, `run(case)`, optional `enabled` |
| `miros/geometry/` | `caps.py` (boundary loops → caps), `centerlines.py` (Voronoi + Dijkstra), `centerline_tree.py` (annotation in the layout `rom/mesh.py` reads), `remesh.py` (pyacvd), `volume.py` (tetgen), `clip.py` (plane clipping) |
| `miros/rom/`, `miros/rom_extract/` | vendored SimVascular `sv_rom_simulation` / `sv_rom_extract_results`; see `VENDORED.md` in each |
| `miros/rom_model.py` | `build_rom_model()`: surface → caps → centerlines → 0D JSON / 1D input |
| `miros/tuning/windkessel.py` | analytic Windkessel init + fixed-point RCR tuning |
| `miros/io/` | the only readers/writers for `rcrt.dat`, `.flow`, 0D JSON, OneDSolver runs |
| `miros/ui/` | console output (rich, plain fallback), matplotlib waveform editor |
| `examples/aorta/` | runnable example (`case.yaml`, surface, inflow) + `reference/` from SimVascular for the validation tests |
| `tests/unit`, `tests/integration` | `pytest`; integration tests are `slow`, skip without solvers |

Case directory: `case.yaml`, `work/` (intermediate files), `results/0D`, `results/1D`, `.miros/`.
`work/`, `results/`, `.miros/` are gitignored everywhere.

## Conventions

- Every stage declares its inputs (file hashes + config sections) so the manifest can decide staleness; when adding a stage, register it in `miros/stages/__init__.py` in pipeline order.
- Outlet ↔ vessel mapping always comes from the 0D JSON (`io/zerod.VesselMap`), never from vessel names or sort order.
- Units: geometry in cm, flow mL/s, pressure dyn/cm² internally, mmHg at every user-facing point (`io/zerod.MMHG_TO_CGS`).
- File formats live in `miros/io`; nothing else hand-writes `rcrt.dat` or the inflow file.
- Do not add SimVascular, vmtk, or conda-only dependencies; everything must be pip-installable on all three OSes.
- `python -m pytest tests/unit -q` before committing; the full suite (`pytest`) takes ~2 minutes with OneDSolver present.

## Plan and history

The refactor plan (findings, design, phases) is published as an artifact linked from the
project memory. Phases 0–2 and the tuner core are done; next are the interactive outlet editor
(`miros clip`), a second example of different topology, and PyPI packaging.
