# Handoff

Written 2026-09-08. Read `CLAUDE.md` for the one-page layout and the house
rules; this file is the long version. It exists so a new session can pick the
work up without re-deriving anything: what the pipeline does stage by stage, the
decisions behind the code, the facts that cost hours to find, what is broken,
and what to do next.

---

## 1. What MIROS is

A vessel surface or a CT/MR volume goes in; patient-specific 0D and 1D
haemodynamic simulations come out. It is standalone: no SimVascular install is
needed. The only external pieces are `pysvzerod` (pip, from git), the
`svOneDSolver` executable, and optionally SeqSeg for segmentation. Everything
SimVascular used to do for us is either vendored (its reduced-order model
builder, pure Python, in `miros/rom` and `miros/rom_extract`) or reimplemented
(caps, centerlines, remeshing, volume meshing).

One command runs a case, one file configures it, and nothing prompts.

---

## 2. Where everything is

| What | Where |
|---|---|
| Repo | `/home/bg2881/Documents/MIROS`, branch `main` |
| Remote | `git@github.com:BryannGan/MIROS.git` |
| Python | conda env `MIROS`, `/home/bg2881/miniconda3/envs/MIROS` (3.11), installed editable |
| 1D solver | `/usr/local/sv/oneDSolver/2025-07-02/bin/OneDSolver` |
| SimVascular | `/usr/local/sv/simvascular/2025-06-21` — a reference to read, never a dependency |
| Segmentation weights | `~/.miros/models` (492 MB), override with `MIROS_MODELS_DIR` |
| Maintainer's cases | `~/miros_cases/{KDR12, HOCMCT009_s10_ph000, clipped_aorta}` |
| Example used by tests | `examples/aorta` (surface, inflow, `case.yaml`, `reference/` from SimVascular) |
| Local scratch, gitignored | `test_Linux_Mac/`, `optimization_testing/` |

Always use that interpreter. The system Python has none of this.

```bash
/home/bg2881/miniconda3/envs/MIROS/bin/python -m pytest tests/unit -q                       # ~3 s, 36 tests
QT_QPA_PLATFORM=offscreen /home/bg2881/miniconda3/envs/MIROS/bin/python -m pytest tests -q  # ~80 s, 48 tests
```

`set -o pipefail` whenever you pipe a test command, or a failure reads as a pass.

---

## 3. Commands

```bash
miros doctor                          # packages, solvers, downloaded models
miros init DIR --surface S --inflow F # write a case.yaml
miros run DIR [--from STAGE] [--until STAGE] [--force]
miros status DIR                      # which stages are fresh, stale, never run
miros models list | download NAME     # SeqSeg weights from Zenodo
miros gui [DIR]                       # the whole workflow in one window
miros setup DIR                       # the window opened on the Targets step
miros show caps DIR                   # 3D view of the caps
miros inflow edit DIR                 # the waveform editor alone
python -m miros ...                   # same, without the console script
```

---

## 4. The pipeline

Ten stages, in this order. Each declares its inputs so the manifest can decide
whether it is stale, and returns the files it wrote.

| Stage | Runs when | Reads | Writes |
|---|---|---|---|
| `segment` | `segmentation.image` is set | the image, the seeds, the model folder | `work/seqseg_surface.vtp`, `work/outlets_proposed.json`, optionally `work/seqseg_centerline.vtp` |
| `preprocess` | always | that surface or `model.surface`, the cuts | `work/surface.vtp`, `work/caps.json`, `work/caps_and_wall/*.vtp` |
| `inflow` | always | `inflow.file`, or the editor | `work/inflow.flow` |
| `rom_model` | always | surface, caps, inflow | `work/extracted_centerlines.vtp`, `work/centerlines_outlets.dat`, `work/0D_solver_input.json` |
| `tune` | always | the 0D model, targets | `work/rcrt.dat` |
| `sim_0d` | always | the 0D model, `rcrt.dat` | `work/0D_solver_input_tuned.json`, `results/0D/0D_results.csv` |
| `extract_0d` | always | the 0D results | `results/0D/0D_statistics.csv`, `0D_summary.json`, `0D_outlets.png` |
| `volume_mesh` | `outputs.volume_projection` and `simulation.run_1d` | the surface | `work/mesh-complete/*` |
| `sim_1d` | `simulation.run_1d` | the 1D input | `work/1D_solver_input.in`, `work/1d_model.vtp`, `results/1D/onedsolver.log` |
| `extract_1d` | `simulation.run_1d` | the 1D results, centerlines | `results/1D/extracted_results*.csv/.vtp/.vtu` |

Adding a stage means writing `inputs(case)`, `outputs(case)`, `run(case)`, and
optionally `enabled(case)` and `disabled_reason(case)`, then registering it in
`miros/stages/__init__.py` in pipeline order. `Stage` also has `optional=True`,
which makes a failure a warning instead of the end of the run; `volume_mesh`
uses it so a tetgen problem cannot cost you the 1D simulation.

### Staleness

`miros/manifest.py` hashes each stage's declared inputs (file contents plus the
relevant config sections) and records them with the outputs. A stage is `never`
if it has no record, `stale` if an output is missing or any input hash changed,
`fresh` otherwise. `Case.run(from_stage=, until=, only=, force=)`: `force` runs
everything in range, `from_stage` forces from there down, `only` restricts to
named stages. The Outlets step uses `only=['preprocess']` so applying cuts does
not re-run a twenty-minute segmentation.

---

## 5. The case file

`case.yaml` is the whole interface. `miros/config.py` holds the schema as
dataclasses, a strict loader with type coercion, and the template.

- **`segmentation`**: `image`, `units` (cm|mm), `model`, `seeds`
  (`{point, direction, radius}`, direction is a second point further along the
  vessel), `config_name`, `max_steps`, `max_branches`, `max_steps_per_branch`,
  `assembly_threshold`, `extract_centerline`, `outlet_back_off`.
- **`model`**: `surface` (null when segmenting), `units`, `inlet`, `cap_names`,
  `outlets` (the reviewed cuts), `smooth_iterations`, `smooth_pass_band`,
  `remesh`, `remesh_edge_size`.
- **`inflow`**: `source` (file|gui), `file`, `heart_rate_bpm`,
  `points_per_cycle`, `peak_flow_mL_s`.
- **`boundary_conditions`**: `mode` (tune|file), `file`, `flow_split`,
  `pressure_mmHg` (`at`, `systolic`, `diastolic`, `mean`), `tolerance_pct`,
  `max_iterations`, `rp_fraction`, `tuning_cycles`.
- **`simulation`**: `cycles`, `seg_min_num`, `element_size`, `save_data_freq`,
  `density`, `viscosity`, `material`, `run_1d`, `max_1d_retries`.
- **`outputs`**: `volume_projection`, `plots`.

Rules that are easy to trip over:

- **Empty is allowed, missing is not.** `flow_split` and `segmentation.seeds`
  may be empty at load time, because a case created from an image has neither
  yet. The stage that needs them raises with an explanatory message instead.
- **Image cases ignore `model.units`**; `segmentation.units` governs, since the
  geometry is in image coordinates until preprocess converts it.
- **PyYAML parses `1.0e7` as a string.** The loader coerces types for this
  reason; keep `1.0e+7` in the template.
- Edits from the GUI go through `miros/config_edit.py` (ruamel round-trip), so
  comments survive: `update_case_yaml`, `set_values` (dotted keys), `set_seeds`,
  `set_outlets`.

Case directory: `case.yaml`, `input/`, `work/` (intermediates), `results/0D`,
`results/1D`, `.miros/manifest.json`. Everything but `case.yaml` and `input/` is
gitignored.

---

## 6. Module map

| Path | What it owns |
|---|---|
| `miros/config.py` | schema, strict loader, template |
| `miros/case.py` | case paths, the stage runner, `StageError` |
| `miros/manifest.py` | content hashes, freshness |
| `miros/stages/` | one module per stage |
| `miros/geometry/caps.py` | reading and writing polydata, boundary loops, `Cap`, `make_caps` |
| `miros/geometry/centerlines.py` | the standalone centerline backend |
| `miros/geometry/centerline_tree.py` | the annotation the vendored ROM builder expects |
| `miros/geometry/outlets.py` | finding vessel ends, proposing cuts |
| `miros/geometry/clip.py` | box cuts, cap naming |
| `miros/geometry/smooth.py` | windowed sinc smoothing |
| `miros/geometry/remesh.py`, `volume.py` | pyacvd remesh, tetgen volume mesh |
| `miros/rom/`, `miros/rom_extract/` | vendored SimVascular; see the `VENDORED.md` in each for every change |
| `miros/rom_model.py` | `build_rom_model()`: surface to 0D JSON and 1D input |
| `miros/tuning/windkessel.py` | boundary condition tuning |
| `miros/io/` | the only readers and writers for `rcrt.dat`, `.flow`, the 0D JSON, OneDSolver runs; `process.py` runs any external program streamed, logged and stoppable |
| `miros/ui/` | console output, waveform editor, the window |
| `miros/models.py` | the SeqSeg weight registry and downloader |
| `miros/timestep.py` | the CFL-based samples-per-cycle recommendation |
| `miros/solvers.py` | finding OneDSolver and pysvzerod on this machine |
| `miros/config_edit.py` | ruamel round-trip edits to `case.yaml` |

---

## 7. Geometry, in the order the pipeline uses it

**Caps.** `boundary_loops` pulls the open loops with `vtkFeatureEdges` plus
`vtkStripper`; the stripper's `MaximumLength` is set to the point count because
its default of 1000 splits a finely meshed cap into several bogus ones.
`make_caps` triangulates each loop and returns `Cap` objects with area, radius,
centroid, normal and name. The inlet is either named or the largest cap.

**Centerlines.** `compute_centerlines` is our own: a Voronoi diagram of the
closed surface's points gives medial vertices (inside test by normals, radius by
distance to the generator), Dijkstra with cost `length / radius` grows a
single-source tree, then Laplacian smoothing, per-tract resampling, and radii
re-measured against the wall.

**The annotation contract** in `centerline_tree.py` is what the vendored ROM
builder reads, and it is exact: `BranchId` and `BifurcationId` with blanking,
`CenterlineId` columns, a `Path` per branch, two-point cells oriented
downstream, outlet endpoints in the order of `centerlines_outlets.dat`,
`GlobalNodeId`, and cross-sections taken by plane cut, choosing the loop that
contains the point, median filtered, with `A/(pi r^2)` clipped to `[1, 3]`.
Break any of it and the 0D model comes out subtly wrong rather than failing.

**Finding vessel ends.** Two ways, in `outlets.py`.
`propose_outlet_planes` reads a tracked centerline (SeqSeg's, when it wrote
one): line cells first, `CenterlineId` only as a fallback, since SeqSeg writes a
single column of branch labels where SimVascular writes one column per path.
`propose_from_closed_surface` works from the surface alone: decimate to 80k
points, build the Voronoi medial graph pruned at 0.7 of an edge length, root it
at the widest vertex, then grow a tree by repeatedly taking the vertex farthest
from it in radius-normalised geodesic distance. A candidate is a real end only
if its path back to the tree is at least four times its own largest radius long,
which is what rejects bumps on the wall of a wide vessel. That criterion took
five attempts; local maxima and relative tests all failed.

Both return every end found, each with `use` and, when off, a `skipped` reason.
Nothing is discarded, because the Outlets step shows the rejects too.

**Cutting.** `clip_with_planes` takes boxes, not planes, following
SimVascular's box trim (`sv4guiModelUtils::CutByBox`: six half-spaces given to
`vtkClipPolyData`). A cut starts at its origin, reaches `box_length` along the
outward normal and is `box_width` wide. Only wall inside the box can go, and of
that only the piece connected to that vessel end, so a neighbour crossing the
box keeps its wall. The box grows along the vessel until the piece it takes ends
inside it, so a cut part way along a vessel trims it there. A cut taking more
than half the model by area is refused by name. The rim is then projected onto
the cut plane, as SimVascular's `project_opening_to_fit_plane` does, because a
box is not linear along a triangle edge and the clip lands within a triangle of
the plane.

`plane_names_for_caps` matches caps to cuts by closest pairs and gives any
unaccounted cap its own name. It used to demand a one-to-one match and raised
`outlet planes could not be matched one-to-one to caps`, which is what broke the
maintainer's first CT run.

**Smoothing.** `smooth_surface` is `vtkWindowedSincPolyDataFilter` with
SimVascular's parameters: 20 iterations, pass band 0.02, boundary and
feature-edge smoothing off, non-manifold smoothing on, coordinates normalised.
It runs before the cuts so rims are cut from an already smooth wall, and it
returns triangles only, deliberately (see the cell-ordering trap below).

**Volume mesh.** tetgen, with 1-based `GlobalNodeID` on the volume and the ids
the exterior inherits from it. Do not renumber the exterior: the result
projection reads `GlobalNodeID - 1` as an index into the volume.

---

## 8. The mapping rule that started the refactor

Outlet caps map to 0D vessels **only** through the 0D JSON:
`vessels[].boundary_conditions.outlet == "RCR_k"`, where `k` is the index in
`centerlines_outlets.dat`. The original code inferred it from sorted branch
names, which included the inlet trunk and interior branches, so every cap read
the wrong vessel. Never reintroduce name or sort-order inference. `io/zerod.py`
`VesselMap` is the one implementation.

---

## 9. Tuning

`miros/tuning/windkessel.py`. An analytic Windkessel initialisation, then a
fixed-point loop, typically three to six 0D solves where the old CMA-ES took
about 1800.

Initialisation: net resistance from mean pressure over mean flow, minus the path
resistance; total compliance from the diastolic decay time; per-outlet
compliance in proportion to flow share; the proximal fraction starts at the
smaller of the configured value and what the target pulse pressure allows.

Each iteration measures the 0D result and moves four knobs: the flow split
scales each resistance by `(q_i / s_i)^alpha`; the level moves all resistance by
the ratio of target to measured `(systolic + diastolic)`, or by mean pressure
when a mean is given; the pulse moves the proximal fraction, and compliance
takes over once the fraction hits a bound; the shape moves compliance by the
ratio of `(mean - diastolic) / pulse pressure`. Compliance is bounded to
`[1e-5, 5e-3]`, the fraction to `[0.01, 0.5]`. The best iterate is kept, and the
loop stops when four iterations fail to improve by 0.3.

Two honest limits, both reported rather than hidden:

- **The inlet pulse pressure has a floor** set by the inflow waveform and vessel
  inertia. On the example, 120/80 is unreachable and the best is about 129/75.
- **Outlet mean pressures are nearly identical** by physics: the path resistance
  drops are 0.08 to 0.41 mmHg. This is correct, not a bug, and it was
  investigated once already.

An audit fixed two real errors here: the level was pinned to an assumed mean,
and the shape knob's sign was inverted.

---

## 10. The window

`miros/ui/app.py`, about 1300 lines, plus `segment_page.py` and
`outlets_page.py`. Seven tabs, addressed by the `MainWindow.TAB_*` constants,
never by number:

`TAB_SEGMENT, TAB_OUTLETS, TAB_MODEL, TAB_INFLOW, TAB_TARGETS, TAB_RUN, TAB_RESULTS = range(7)`

- **Segment**: image, slices, model download, seeds, tracing settings, and the
  full SeqSeg config behind "all settings…" which saves a per-case copy at
  `input/seqseg_config.yaml`.
- **Outlets**: every vessel end found, solid where it will be cut and faint
  where it will not, with tick, inlet choice, rename, nudge, flip, box size, and
  Apply. Writes `model.outlets`.
- **Model**: still the surface-import page. It is where an image case lands
  after cutting, which is wrong (see the backlog).
- **Inflow**: the embedded matplotlib editor with 20 draggable control knots,
  heart rate, peak flow, samples per cycle with a CFL recommendation.
- **Targets**: cap names, inlet, flow shares, pressure target and anchor.
- **Run**: 0D only or 0D and 1D, optional volume projection, stage table,
  progress bar, Stop button, log.
- **Results**: 1D pressure or flow, on the wall or the centerline, time slider,
  cycle mean, per-outlet table.

### Progress and Stop

A stage reports where it is with `console.progress(done, total, text)`; the
window installs a handler for the run (`console.set_progress_handler`) and
draws the bar, a terminal gets a `\r` line, piped output a line per tenth.
`console.progress(None)` clears it. Only the segment stage reports today.

Stop is a `threading.Event` created by `start_run`, handed to `Case.run(cancel=)`
and readable by every stage as `case.cancel`. The runner checks it between
stages; `io/process.run_logged` checks it every half second and kills the
program (SeqSeg, OneDSolver) as a whole process tree; the tuner checks it
before each solve. Anything else finishes its stage first, and the button says
so. A stopped stage records nothing in the manifest, so the next Run resumes
there. `RunCancelled` (from `miros.case`) is the signal, and `on_done` callbacks
receive `'done' | 'stopped' | 'failed'`, not a bool. Closing the window during
a run offers Stop as well.

Rules learned the hard way, all of which have regression tests:

- **The worker thread must outlive its own `done` signal.** Emitting from inside
  the thread and dropping the reference gives `QThread: Destroyed while thread
  is still running` and an abort. Keep the object until Qt's `finished`.
- **A subprocess reader thread prints through the redirected stdout too**, so
  `_LineWriter` takes a lock; without it two threads share one line buffer.
- **A `QLabel` that cannot wrap sets the window's minimum width.** A tab
  widget's minimum is its widest page, and a main window cannot shrink below
  it, so one long instruction label made the window 1737 px wide and, on a
  scaled display, wider than the screen and impossible to resize. Every
  sentence-length label gets `setWordWrap(True)`, rows of many controls are
  split, and the window opens at no more than 90% of the screen.
  `test_window_fits_a_laptop_screen` holds every page under 900 px.
- **No stage may open a window off the main thread.** `console.set_interactive
  (False)` during GUI runs; the inflow stage checks it before opening the
  editor.
- **Rich must be silenced** in the GUI log: `console.set_plain(True)`, or ANSI
  escapes appear in the pane.
- **Picking is enabled once.** `Viewer.clear()` disables it first, or pyvista
  raises "Picking is already enabled".
- **Seed picking uses a Qt event filter**, not VTK observers, because VTK gives
  the rotation style exclusive focus between press and release, so a release
  observer never fires. Press and release within 4 px counts as a click;
  anything longer stays a rotation.
- **Volumes are shown as three `vtkImageActor`s**, moved by display extent.
  Cutting polygonal slices costs about 1.1 s per slider step on a 512x64x512
  scan against 1 ms this way.
- **matplotlib handlers must be kept alive** or the control points stop being
  draggable when the handler is collected.
- The viewer style, which the maintainer likes and asked to keep: light grey
  wall at 0.5 opacity, crimson inlet, steel blue outlets, gold selection,
  labels at font size 12 with 0.6 shape opacity.

---

## 11. SeqSeg

`stages/segment.py` runs it as a subprocess so torch and nnU-Net never load into
our process, through `io/process.run_logged`, so its output streams into the log
as it is printed and Stop kills it:

```
python -u -m seqseg.seqseg run single --image IMG --outdir work/seqseg
    --model-folder .../nnUNetTrainer__nnUNetPlans__3d_fullres --train-dataset DATASET
    --config-name NAME_OR_PATH --unit cm|mm --scale S
    --max-n-steps N --max-n-branches N --max-n-steps-per-branch N
    --assembly-threshold T --extract-global-centerline 0|1 --cap-surface-cent 0
    --seeds-json work/seqseg/seeds.json
```

`seeds.json` is `[{"name": <image stem>, "seeds": [[start, direction, radius]],
"cardiac_mesh": false}]`, and the name must match the image stem.

The facts that cost time:

- **SeqSeg's step counter is not on its stdout.** Unless the config's `DEBUG` is
  true, `pipeline/classic.py` points `sys.stdout` at `out.txt` in its scratch
  tree (`work/seqseg3d_fullres_<case>/out.txt`) for the whole trace, so the
  pipe carries only nnU-Net's per-prediction tqdm bars, warnings, and the
  opening and closing lines. `DEBUG: true` is no way out: it calls
  `pdb.set_trace()` at `DEBUG_STEP` (63 in `global_aorta`). So `_Tracing` in
  the segment stage tails `out.txt` for `*** Step number N ***` and counts
  `Post Branches are` for the branch number; Python buffers that file, so the
  counter moves every three or four steps. `-u` is passed so the lines that do
  come down the pipe arrive when printed, and the tqdm bars are dropped from
  the log (one per step, hundreds of them).
- **SeqSeg 2.1's `global` config is missing `ADD_RADIUS`**, which its own tracer
  reads, so a run dies about a minute in with a `KeyError`. `global_debug` is
  the same. Each model in `models.py` names a working config (`global_aorta`,
  `global_coro`) and `_config_name` validates the choice against the fullest
  config it can find, before the run.
- **`--config-name` accepts an absolute path** with `.yaml` removed, which is
  how the per-case edited config works.
- **`run single` writes no centerline** unless `--extract-global-centerline 1`.
  Pass it: the tree it returns is one cell per branch with radii, and it finds
  ends much better than reading the surface. `--cap-surface-cent 1` crashes
  inside SeqSeg's capping, so it is pinned off.
- **SeqSeg writes into two places**: the smoothed surface into `--outdir`, and a
  scratch tree into a sibling directory whose name is the outdir string with
  `3d_fullres_<case>` appended. Both are cleared before a run.
- **Its output surface is not clean.** The maintainer's CT gave 36 disconnected
  pieces and non-manifold edges on 2M points.
- **Its post-trace phase can eat all the memory.** A 12-step trace of KDR12
  with `extract_centerline` on wrote its surface, then grew to 23 GB in the
  global centerline extraction and was OOM-killed three minutes later (exit
  -9; the stage names that cause). The 797-step run of the same image
  survived. Short test runs should switch the centerline off.
- **Weights** are on Zenodo, CC-BY-4.0: aorta CT and MR in one 236 MB archive
  (record 15020477), coronary CT in a 3 MB one (record 19547894). `models.py`
  resolves a registry name in the model store before treating it as a path, so a
  directory of the same name in the working directory cannot shadow it.
- **A VTK volume (`.vti`, `.vtk`) is converted** once to `.mha` in `work/`,
  keeping spacing, origin and direction, because SeqSeg reads what SimpleITK
  reads.
- Cost on the maintainer's machine, an RTX 4060 Ti: about 1.4 s per step, so
  their 797-step CT run took 18 minutes.

---

## 12. Numbers to compare against

The SeqSeg tutorial MR aorta, `0110_0001.mha`, seed
`point [-2.07367, -2.1973, 13.4288]`, `direction [-1.17086, -1.33526, 12.2407]`,
`radius 1.1`, units **cm**, model `aorta_mr`, `max_steps: 80`:

| Step | Cost | Result |
|---|---|---|
| SeqSeg | ~70 s | closed surface, 322k points |
| ends from its centerline | seconds | 8 branch tips with radii |
| preprocess (smooth, cut, caps) | 14 s | inlet 4.50 cm², seven outlets |
| smoothing alone | included | wall moves 0.25 mm |
| the whole Segment step in the window | 72 to 77 s | lands on the caps |

The maintainer's CT aorta, `~/miros_cases/KDR12`, 2M points after segmentation:
smoothing 3 s and 0.05 mm, 41 ends found in 25 s, 20 proposed, 20 cuts in 87 s
keeping 94% of the surface.

Validation against SimVascular lives in `tests/integration/
test_centerlines_vs_simvascular.py`: identical topology, path lengths within 3%,
end areas equal to cap areas, and 0D flow splits reproducing the reference.

---

## 13. What to do next

From a systematic review of the clinician's path, image to results, roughly in
the order I would take them.

Done since the review: segmentation streams into the log with a step counter,
rate and bound on the time left, and the Run step has a Stop button (section
10, "Progress and Stop").

1. **The Outlets review can be skipped.** Run on the Run step from a fresh image
   case segments and then clips with the automatic proposals, unseen. Gate the
   clip on reviewed cuts, or say so on the Run step.
2. **Half the settings are invisible**, reachable only by editing `case.yaml`:
   smoothing passes and pass band, remesh and edge size, outlet back-off,
   assembly threshold, blood density and viscosity, cardiac cycles, tuning
   tolerance and iterations, 1D element size and segments per branch.
3. **No way to inspect or repair a segmentation.** Nothing reports disconnected
   pieces or openings, or offers keep-largest-body, hole filling, or a smoothing
   preview. A Surface panel between Segment and Outlets is the natural home.
4. **A cut cannot be added where no candidate was found.** Trimming at a chosen
   level needs hand-edited YAML.
5. **Nothing sanity-checks before a long run**: an implausible cap area, a flow
   split missing an outlet, a sample count under the CFL recommendation.
6. **Redrawing is wasteful.** Every tick or nudge on the Outlets step rebuilds
   the whole wall actor, seconds per click on 2M points. Draw the wall once.
7. **Nothing decimates.** Full segmentation resolution is carried through
   cutting, centerlines and meshing; about 200k points would speed the rest.
8. **Two tabs are both numbered 1**, and the Model step still shows the
   surface-import form with a units dropdown that image cases ignore.
9. **No report.** One page with the model, per-outlet pressures and flows, the
   tuned boundary conditions and the waveform would finish the workflow.
10. **Only segmentation reports progress.** The cuts on a 2M-point surface
    (87 s on KDR12), the tuner's solves and the 1D solve run behind a busy bar;
    each has a natural counter (cuts done, iterations, solver time steps).

---

## 14. Known defects, not yet fixed

- `geometry/centerline_tree.py::_blank_regions` can leave a one-node tract when
  two splits sit very close, which divides by a zero path length and puts NaN
  into the 0D JSON and the 1D input. Needs a real fix in the blanking.
- `case.py` records absolute output paths in the manifest, so moving a case
  directory makes everything stale.
- `solvers.py` picks the OneDSolver binary by lexical path order (`sorted(found)[-1]`), which is right for dated directories and wrong for anything else.
- Edits made in the window during a run are ignored: the worker holds its own
  `Case`.
- `centerline_tree.py` emits `GlobalNodeId` permuted by the resampling order,
  documented as "the point index". `rom/mesh.py` relies on the inlet's id being
  zero, which happens to hold.
- `rom/mesh.py` adaptive segmentation needs more points than segments; a branch
  with two or three unblanked points gets arbitrary breakpoints.

---

## 15. Traps

- **Never patch a file with a heredoc that opens it for writing before it can
  fail.** `open(..., 'w')` truncates, then the script raises, and the file is
  gone. This happened three times. Use the editing tools.
- **VTK numbers polydata cells verts, then lines, then polys.** Indexing cells
  by row of the polygon array breaks the moment a line cell exists, and cleaning
  makes one from a degenerate triangle. `clip.py::triangles_only` exists for
  this; skipping it caused a segfault that a review caught.
- **`pv.PolyData.bounds` includes unreferenced points.** After a clip, measure a
  cleaned copy or you will chase a ghost.
- **Never let a test write into `examples/aorta`.** Copy it to a temp directory.
- **The vendored ROM reader requires the boundary condition file to be named
  exactly `rcrt.dat`** next to the outputs, and it must name the current caps: a
  stale one from renamed caps raises a `KeyError` deep in the 0D writer.
- **A `.flow` file's time column needs `%.9f`.** At `%.6f` the timestep read
  back drifts enough over a cycle that the extractor picks the wrong one.
- The maintainer is **cost-sensitive about spawning agents**. One focused review
  is welcome; a fan-out of a dozen is not. A review that was killed still
  returned findings worth acting on.
- **Verify on real data before claiming anything works.** The tutorial aorta and
  `~/miros_cases/KDR12` fail differently, and only the second one found the
  cutting bugs.

---

## 16. How the code got here

| Commit | What landed |
|---|---|
| `0af8544` | the outlet-to-vessel mapping fix, phase 0 |
| `a036767` | the standalone geometry core, no SimVascular imports |
| `dbeabcc` | `case.yaml`, the manifest, the stage runner, the CLI |
| `33c5896` | the physics-first boundary condition tuner |
| `dcc7c3d` | segmentation from an image, model download, automatic outlet cuts |
| `d04ad75` | the Segment step in the window, plus fifteen review fixes |
| `ada0872` | seed picking that survives a drag |
| `88286ca` | the working tracing config, VTK images, the fast slice view |
| `87a2ace` | typed image paths, Qt's own file dialogs, no dtype copies |
| `fceffea` | the Outlets step: cuts proposed, then approved |
| `d314650` | box cuts and wall smoothing, both after SimVascular |
| `8ff0f36` | three regressions in the box cut, found by review |

`tests/manual/` holds the checks that need a window or a real segmentation: the
surface case end to end, the Segment step with a real SeqSeg run, the Outlets
step, seed picking under real Qt mouse events, Stop during a real segmentation,
and a slice benchmark. They read `MIROS_TUTORIAL`, `MIROS_IMAGE` and
`MIROS_CASE`; see `tests/manual/README.md`. The tutorial MR image is not on
this machine any more; `smoke_stop.py` works from `~/miros_cases/KDR12`.
