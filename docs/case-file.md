# The case file

`case.yaml` is the whole interface: every answer the pipeline needs lives in it, and `miros run`
never asks anything. `miros init` writes it with the caps it detected and every option commented;
the window edits it in place, keeping your comments. Unknown keys are errors, values are checked
before anything runs, and paths are relative to the file's directory.

Rules that are easy to trip over:

- **Empty is allowed, missing is not.** `flow_split` and `segmentation.seeds` may be empty when
  the file is loaded, because a case created from an image has neither yet; the stage that needs
  them stops with a message saying so.
- **An image case ignores `model.units`.** `segmentation.units` governs, since the geometry is in
  image coordinates until the preprocess stage converts it.
- **Write `1.0e+7`, not `1.0e7`.** PyYAML reads the latter as a string.
- Caps are named `cap_1, cap_2, …` in decreasing-area order; `cap_names` renames them in that
  order, and `flow_split` and `pressure_mmHg.at` use the new names.

## The template

What `miros init` writes, here for a surface with an inlet and two outlets:

<!-- template:begin -->
```yaml
# MIROS case file. Every answer the pipeline needs lives here; `miros run`
# never asks anything. Paths are relative to this file's directory.
name: case

segmentation:                   # optional: segment the vessel from an image with SeqSeg
  image: null                # null = start from model.surface
  units: mm          # units of the image coordinates (cm | mm)
  model: aorta_ct            # aorta_ct | aorta_mr | coronary_ct | path to an nnU-Net trainer folder
  seeds: []
  #  - {point: [x, y, z], direction: [x2, y2, z2], radius: 1.1}   # world coordinates; direction = a second
  #                                                              point a little further along the vessel
  config_name: ''               # SeqSeg tracing config; '' picks the one that suits the model
  max_steps: 1000               # total tracing steps: how much of the tree SeqSeg follows
  max_branches: 100             # how many branches it may start
  max_steps_per_branch: 100     # how far it follows one branch before moving on
  assembly_threshold: 0.5       # probability at which the assembled segmentation becomes the surface
  extract_centerline: true      # let SeqSeg centerline the whole tree (the outlet cuts then come from it)
  outlet_back_off: 2.5          # radii to walk back from each vessel end before cutting it open

model:
  surface: input/surface.vtp            # null when the surface comes from segmentation
  units: cm                # cm | mm  (mm models are converted to cm)
  inlet: cap_1                # cap name; null = the largest cap
  # caps are named cap_1, cap_2, ... in decreasing-area order; give your own
  # names here (same order) if you prefer, e.g. [aorta_root, desc_aorta, ...]
  cap_names: null
  outlets: []                   # cut planes: reviewed on the Outlets step of `miros gui`
  smooth_iterations: 0          # windowed sinc passes over the wall; 20 for a segmented surface,
                                # 0 for a surface you have already prepared elsewhere
  smooth_pass_band: 0.02        # what the smoothing keeps: 0.001 very smooth, 0.1 barely anything
  remesh: false                 # usually unnecessary; centerlines work on the raw surface
  remesh_edge_size: null

inflow:
  source: file       # file | gui
  file: input/inflow.flow
  heart_rate_bpm: 60            # gui only
  points_per_cycle: 1200        # gui only
  peak_flow_mL_s: null          # gui axis bound

boundary_conditions:
  mode: tune                    # tune | file (file: give an rcrt.dat below)
  file: null
  flow_split:                   # percent of flow per outlet, must sum to 100
    cap_2: 50
    cap_3: 50
  pressure_mmHg:
    at: inlet                   # 'inlet' or an outlet name
    systolic: 120
    diastolic: 80
    mean: null                  # optional third target
  tolerance_pct: 5
  max_iterations: 12
  rp_fraction: 0.09             # Rp / (Rp + Rd)
  tuning_cycles: 5              # 0D cycles per tuning solve

simulation:
  cycles: 6
  seg_min_num: 4
  element_size: 0.01
  save_data_freq: 5
  density: 1.06
  viscosity: 0.04
  material:                     # Olufsen 1999 defaults
    olufsen_k1: 0.0
    olufsen_k2: -22.5267
    olufsen_k3: 1.0e+7
    olufsen_exponent: 1.0
    olufsen_pressure: 0.0
    linear_ehr: 1.0e+7
    linear_pressure: 0.0
  run_1d: true
  max_1d_retries: 3

outputs:
  volume_projection: false      # tetgen volume mesh + 3D projection of 1D results
  plots: true

solvers:
  onedsolver: null      # path to the OneDSolver executable; null = search
```
<!-- template:end -->

## Section by section

| Section | What it holds |
|---|---|
| `segmentation` | the image, its units, the model, the seeds, SeqSeg's tracing settings, and how far to back off from a vessel end before cutting; see [From an image](segmentation.md) |
| `model` | the surface (or `null` when it comes from segmentation), units, the inlet, cap names, the reviewed cuts, smoothing and remeshing |
| `inflow` | a `.flow` file (time in seconds, flow in mL/s, one cycle) or the editor's waveform with heart rate and samples per cycle |
| `boundary_conditions` | targets for the tuner, or an `rcrt.dat`; see [Tuning](tuning.md) |
| `simulation` | cycles, 1D discretisation, blood density and viscosity, the vessel wall material, whether to run the 1D solver |
| `outputs` | whether to project the 1D results onto a tetrahedral lumen (VTU), whether to plot |
| `solvers` | the path to `OneDSolver` when it is not found automatically |
