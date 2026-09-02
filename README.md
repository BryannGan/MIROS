# MIROS

**Medical Image to Patient-Specific Reduced-Order Hemodynamic Model Simulation in Minutes**

MIROS turns a vessel surface segmented from volumetric angiography (for example with
[SeqSeg](https://github.com/numisveinsson/SeqSeg)) into patient-specific 0D and 1D blood-flow
simulations: it computes the centerlines, builds the reduced-order models, tunes the outlet
boundary conditions to the flow distribution and pressures you specify, runs the
[svZeroDSolver](https://github.com/simvascular/svZeroDSolver) and
[svOneDSolver](https://github.com/SimVascular/svOneDSolver) solvers, and extracts the results —
from one command, with every input in one file.

*(Manuscript in preparation.)*

```
$ miros run examples/aorta
```

---

## What it does

```
surface, clipped open at the inlet and outlets
   │  preprocess   caps (area, centroid, normal), unit conversion, optional remesh
   │  inflow       one cardiac cycle from a file or the interactive editor
   │  rom_model    centerlines (Voronoi medial axis + shortest paths), 0D model
   │  tune         RCR boundary conditions from flow splits + pressure targets
   │  sim_0d       svZeroDSolver
   │  extract_0d   per-outlet statistics and plots
   │  sim_1d       1D model + svOneDSolver
   │  extract_1d   last-cycle CSV / VTP (/ VTU) with pressures in mmHg
   ▼
results/0D, results/1D
```

MIROS does not need a SimVascular installation. The reduced-order model builder from SimVascular
is vendored (see `miros/rom/VENDORED.md`); centerlines, caps, remeshing and volume meshing are
implemented on VTK, SciPy, pyacvd and tetgen.

## Requirements

| What | Why | How |
|---|---|---|
| Python ≥ 3.9 | | conda or venv |
| `pysvzerod` | 0D solver | `pip install git+https://github.com/simvascular/svZeroDSolver.git` |
| `svOneDSolver` executable | 1D solver | [SimTK download](https://simtk.org/frs/index.php?group_id=188) or build from source; `miros doctor` finds it on `PATH`, in the usual install locations, or via `MIROS_ONEDSOLVER` |
| a display | only for `miros setup`, `miros show caps` and `miros inflow edit` | |
| `pyvistaqt` + `PySide6` | only for `miros setup` | `pip install "miros[gui]"` (or `pip install pyvistaqt PySide6`) |

Everything else is on PyPI and installed automatically. SeqSeg (the segmentation step that
produces the input surface) is a separate package and is not required to run MIROS.

## Install

Until MIROS is on PyPI, install from the repository:

```bash
git clone https://github.com/BryannGan/MIROS.git
cd MIROS
conda create -n MIROS python=3.11 && conda activate MIROS     # or any venv
pip install -e .
pip install git+https://github.com/simvascular/svZeroDSolver.git
miros doctor                                                # checks packages and finds OneDSolver
```

Linux, macOS and Windows use the same code path; there is nothing to configure per OS.

## Quick start: the example

```bash
miros run examples/aorta
```

This runs the whole pipeline on the bundled aortic-arch case (about two minutes; the 1D solve
is most of it). Nothing is asked at run time. Afterwards:

```
examples/aorta/
├── case.yaml                     the inputs (read it — it is commented)
├── work/                         caps, centerlines, 0D/1D solver inputs, rcrt.dat, tuning_report.json
└── results/
    ├── 0D/                       0D_results.csv, 0D_statistics.csv, 0D_summary.json, 0D_outlets.png
    └── 1D/                       solver outputs, extracted_results_{flow,pressure,area}.csv,
                                  extracted_results_pressure_mmHg.csv, extracted_results.vtp
```

Run it again and nothing happens — every stage records what it read, and only stale stages
re-run. Change a pressure target in `case.yaml` and only `tune` onward re-runs.

```bash
miros status examples/aorta        # which stages are fresh / stale and why
miros run examples/aorta --from tune
```

## Your own case

```bash
miros init ~/cases/patient01 --surface /path/to/clipped_surface.vtp --inflow /path/to/inflow.flow
```

`init` finds the caps of the surface, names them `cap_1, cap_2, …` in decreasing-area order,
proposes the largest as the inlet, and writes a commented `case.yaml` with equal flow splits.
The flow splits and the pressure targets are the parts that are yours; set them either in the
3D setup window or by editing the file, then run:

```bash
miros setup ~/cases/patient01      # 3D view + form: name caps, choose the inlet, flow shares,
                                   # pressure anchor and targets; Save writes case.yaml
miros run ~/cases/patient01
```

`miros setup` needs the GUI extra (`pip install "miros[gui]"`, i.e. `pyvistaqt` and `PySide6`);
without it, edit `case.yaml` by hand — it is the same information.

Inputs:

- **Surface** (`.vtp`, `.stl` or `.ply`): the vessel wall, *open* at the inlet and at every
  outlet, so that each boundary loop is a cross-section. Units `cm` or `mm` (`model.units`;
  mm is converted). A closed SeqSeg surface can be opened by cut planes listed under
  `model.outlets`; an interactive editor for those is on the roadmap.
- **Inflow** (`.flow`): two columns, time [s] and flow [mL/s], one cardiac cycle. Draw one with
  `miros inflow edit ~/cases/patient01` if you do not have a measurement (`init … --inflow-source gui`
  when you have no file yet; the drawn waveform is saved and reused, redraw any time).
- **Boundary conditions**: either targets (`mode: tune`) or your own `rcrt.dat` (`mode: file`).

`miros show caps ~/cases/patient01` is the read-only version of the setup view.

## The case file

```yaml
model:
  surface: clipped_surface.vtp
  units: cm                     # cm | mm
  inlet: cap_1                  # null = largest cap
  cap_names: null               # your own names for the caps, in decreasing-area order

inflow:
  source: file                  # file | gui
  file: inflow.flow

boundary_conditions:
  mode: tune                    # tune | file
  flow_split: {cap_2: 50, cap_3: 20, cap_4: 10, cap_5: 10, cap_6: 10}   # percent, sums to 100
  pressure_mmHg: {at: inlet, systolic: 130, diastolic: 75, mean: null}  # at: inlet or an outlet
  tolerance_pct: 5

simulation:
  cycles: 6                     # cardiac cycles to simulate; the last one is extracted
  run_1d: true

outputs:
  volume_projection: false      # also paint 1D results onto a tetrahedral lumen (VTU)

solvers:
  onedsolver: null              # path; null = search
```

Unknown keys are errors, values are validated before anything runs, and paths are relative to
the case directory. The full template with every option is what `miros init` writes.

## Boundary-condition tuning

With `mode: tune`, MIROS finds RCR (three-element Windkessel) parameters for every outlet so
that the 0D model reproduces the flow distribution and the pressure you asked for:

1. **Analytic start** — no solves. From the mean inflow and the target mean pressure the network
   resistance follows; each outlet gets its share according to the flow split (minus the vessel
   resistance on its path). Compliance comes from the diastolic decay time constant and is
   distributed in proportion to flow, so every outlet has the same RC time constant.
2. **Fixed-point loop** — a few 0D solves (a second or two in total). Each iteration measures the
   achieved splits and the pressure waveform and updates the resistances, the proximal fraction
   Rp/(Rp+Rd) and the compliance multiplicatively.

On the example, the flow splits are within 5 % after the first solve and exact by the third.

**Reachable targets.** The pulse pressure at the *inlet* has a floor: part of it is the inertial
and viscous pressure drop along the vessels themselves (the 0D vessels carry inductance and
resistance), which depends on the inflow waveform and the geometry, not on the outlets. With a
waveform that swings from −120 to +610 mL/s, 120/80 at the inlet of the example is not
attainable — the best trade-off is about 129/75, which is why the example targets 130/75. When
a target is out of reach the tuner keeps its best iterate, stops, and tells you why; target an
outlet (`pressure_mmHg.at: cap_2`), use a smoother waveform, or accept the values.
`work/tuning_report.json` records every iteration.

## Commands

| Command | Does |
|---|---|
| `miros doctor` | checks Python packages, finds `OneDSolver`, reports whether a display is available |
| `miros init DIR [--surface S] [--inflow F] [--units mm] [--inlet NAME]` | creates `DIR/case.yaml` with the detected caps |
| `miros run DIR [--from STAGE] [--until STAGE] [--force]` | runs stale stages; `--from` re-runs from a stage onward |
| `miros status DIR` | fresh / stale / never per stage, with the reason |
| `miros setup DIR` | 3D view + form: cap names, inlet, flow shares, pressure anchor and targets → `case.yaml` (needs `miros[gui]`) |
| `miros show caps DIR` | read-only 3D view of the surface with labelled caps |
| `miros inflow edit DIR` | draw the inflow waveform; saved to `inflow.file` and picked up by the next run |

Stages, in order: `preprocess inflow rom_model tune sim_0d extract_0d volume_mesh sim_1d extract_1d`.

Everything is also a library: `miros.case.Case(dir).run()`, `miros.rom_model.build_rom_model(...)`,
`miros.geometry.centerlines.compute_centerlines(...)`.

## Validation

`tests/integration/test_centerlines_vs_simvascular.py` gates the built-in centerline backend
against SimVascular's output on the example (`examples/aorta/reference`): same branches and
junctions, path lengths within 3 %, end-of-branch areas equal to the cap areas, and a 0D model
that reproduces SimVascular's flow splits within 1 percentage point with identical boundary
conditions (measured: 0.4). Run the suite with

```bash
pip install -e ".[dev]"
pytest                         # unit + integration; the 1D tests skip without OneDSolver
pytest -m "not slow"           # unit tests only, a second
```

## Troubleshooting

- `miros doctor` first. A missing `pysvzerod` means the 0D solver was not installed from git; a
  missing `OneDSolver` means the 1D stage is unavailable — set `solvers.onedsolver` or
  `MIROS_ONEDSOLVER`, or set `simulation.run_1d: false`.
- *"Surface has no boundary loops"*: the surface is closed. Clip it open at the inlet and outlets
  (or describe the cut planes under `model.outlets`).
- *"outlet … is not reachable from the inlet through the lumen"*: the surface has a gap or two
  vessels are not actually connected; check it in ParaView.
- *"flow_split names … are not outlets"*: names in `case.yaml` must match the caps `init`
  detected; `miros show caps` shows them.
- A stage that fails leaves earlier stages fresh; fix the input and `miros run` again — only the
  failed stage and its dependants run.

## Roadmap

- Interactive outlet editor (`miros clip`) to open a closed SeqSeg surface without ParaView,
  writing the cut planes to `case.yaml`; then a seed picker for SeqSeg.
- A second example of different topology (carotid or coronary).
- PyPI release; `pysvzerod` wheels upstream so that `pip install miros` resolves everything.

## Citation

MIROS builds on SimVascular, svZeroDSolver, svOneDSolver and SeqSeg:

- Updegrove A. et al., *SimVascular: An Open Source Pipeline for Cardiovascular Simulation*, Ann Biomed Eng 2017.
- Pfaller M.R. et al., *Automated generation of 0D and 1D reduced-order models of patient-specific blood flow*, Int J Numer Meth Biomed Eng 2022.
- Sveinsson Cepero N. & Shadden S.C., *SeqSeg: Learning Local Segments for Automatic Vascular Model Construction*, Ann Biomed Eng 2024. https://doi.org/10.1007/s10439-024-03611-z

## License

MIT (see `LICENSE`). The vendored SimVascular modules keep their own permissive license, reproduced in every file under `miros/rom` and `miros/rom_extract`.
