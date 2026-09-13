# Commands

`miros` and `python -m miros` are the same thing.

| Command | Does |
|---|---|
| `miros doctor` | checks the Python packages, finds `OneDSolver`, lists downloaded models, says whether a display is available |
| `miros models list` / `miros models download NAME` | the pretrained SeqSeg models: `aorta_ct`, `aorta_mr`, `coronary_ct` |
| `miros init DIR --surface S [--inflow F] [--inflow-source gui] [--units mm] [--inlet NAME]` | creates `DIR/case.yaml` with the caps it detects on the surface |
| `miros run DIR [--from STAGE] [--until STAGE] [--force]` | runs the stale stages; `--from` re-runs from a stage onward, `--force` all of them; Ctrl-C stops and the next run resumes |
| `miros status DIR` | fresh, stale or never per stage, with the reason |
| `miros gui [DIR]` | the whole workflow in one window (needs `[gui]`) |
| `miros setup DIR` | the window opened on the Targets step |
| `miros show caps DIR` | a read-only 3D view of the surface with labelled caps |
| `miros inflow edit DIR` | draws the inflow waveform and saves it for the next run |

## The stages

`miros run` executes these in order. Each declares what it reads, so `status` can tell whether
it is fresh; each writes into `work/` or `results/` in the case directory.

| Stage | Runs when | Does |
|---|---|---|
| `segment` | `segmentation.image` is set | SeqSeg from the seeds; proposes where to cut the vessel ends |
| `preprocess` | always | smooths a segmented wall, applies the cuts, finds the caps, converts mm to cm |
| `inflow` | always | one cardiac cycle from `inflow.file` or the editor |
| `rom_model` | always | centerlines (Voronoi medial axis and shortest paths), the 0D model, the 1D input |
| `tune` | always | RCR boundary conditions from the flow split and pressure targets, or from your `rcrt.dat` |
| `sim_0d` | always | svZeroDSolver |
| `extract_0d` | always | per-outlet statistics, summary, plot |
| `volume_mesh` | `outputs.volume_projection` | tetgen lumen mesh for projecting 1D results |
| `sim_1d` | `simulation.run_1d` | the 1D model and svOneDSolver |
| `extract_1d` | `simulation.run_1d` | last-cycle flow, pressure and area as CSV, VTP and optionally VTU |

A stage that fails leaves the earlier ones fresh: fix the input and run again, and only the
failed stage and those after it run.

## The case directory

```
patient01/
├── case.yaml            every input; see docs/case-file.md
├── input/               what you supplied, referenced from case.yaml
├── work/                caps, centerlines, solver inputs, rcrt.dat, tuning_report.json
├── results/0D           0D_results.csv, 0D_statistics.csv, 0D_summary.json, 0D_outlets.png
├── results/1D           solver output, extracted_results_{flow,pressure,area}.csv, extracted_results.vtp
└── .miros/manifest.json what each stage read and wrote, for freshness
```

## As a library

```python
from miros.case import Case
Case('~/cases/patient01').run(until='rom_model')

from miros.rom_model import build_rom_model
from miros.geometry.centerlines import compute_centerlines
```
