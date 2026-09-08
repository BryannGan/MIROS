# Handoff

Written 2026-09-08, after the sessions that added image segmentation and the
outlet editor. Read `CLAUDE.md` first for the layout and conventions; this file
covers what is not obvious from the code, what was decided and why, and what to
do next.

## Where things are

| What | Where |
|---|---|
| Repo | `/home/bg2881/Documents/MIROS`, branch `main`, remote `git@github.com:BryannGan/MIROS.git` |
| Python environment | conda `MIROS` at `/home/bg2881/miniconda3/envs/MIROS` (3.11), package installed editable |
| 1D solver | `/usr/local/sv/oneDSolver/2025-07-02/bin/OneDSolver` |
| SimVascular (reference only, not a dependency) | `/usr/local/sv/simvascular/2025-06-21` |
| Segmentation weights | `~/.miros/models` (492 MB), or `MIROS_MODELS_DIR` |
| The maintainer's own cases | `~/miros_cases/{KDR12, HOCMCT009_s10_ph000, clipped_aorta}` |
| Example that the tests use | `examples/aorta` (surface, inflow, `case.yaml`, SimVascular reference) |

Run everything with that environment's interpreter, not the system one:

```bash
/home/bg2881/miniconda3/envs/MIROS/bin/python -m pytest tests/unit -q     # ~3 s
QT_QPA_PLATFORM=offscreen /home/bg2881/miniconda3/envs/MIROS/bin/python -m pytest tests -q   # ~80 s, needs the solvers
```

`tests/manual/` holds the checks that cannot run headless in CI but do run
offscreen: the window on a surface case, the Segment step end to end (this one
really runs SeqSeg, about 80 seconds on the tutorial), the Outlets step, seed
picking driven by real Qt mouse events, and a slice-view benchmark. They take
their paths from `MIROS_TUTORIAL` and `MIROS_IMAGE`.

The tutorial data those scripts want is the SeqSeg tutorial MR aorta,
`0110_0001.mha`, with the seed
`point [-2.07367, -2.1973, 13.4288]`, `direction [-1.17086, -1.33526, 12.2407]`,
`radius 1.1`, units **cm**, model `aorta_mr`, and `max_steps: 80` to keep a run
to about a minute. It was downloaded from the SeqSeg tutorial data (note the
capital I in `.../data/Images/0110_0001.mha`).

## What the last sessions built

Commits `dcc7c3d` through `36ed2a0`.

- **Segmentation from an image.** `miros/stages/segment.py` runs
  `seqseg run single` as a subprocess so torch never loads into the GUI process.
  `miros/models.py` downloads the pretrained networks from Zenodo.
- **Two new GUI steps.** `ui/segment_page.py` (image, seeds, tracing settings)
  and `ui/outlets_page.py` (review the cuts before anything is clipped).
- **Cuts are boxes**, `geometry/clip.py`, and a segmented wall is smoothed
  first, `geometry/smooth.py`, both following SimVascular.

### Facts that cost time to find

- **SeqSeg 2.1's `global` config is broken.** It has no `ADD_RADIUS`, and its
  tracer reads that key, so a run dies a minute in with a `KeyError`. So does
  `global_debug`. Every model in `models.py` now names a working config
  (`global_aorta`, `global_coro`), and `stages/segment.py::_config_name`
  validates the choice against the fullest config it can find before running.
- **`run single` writes no centerline unless you ask.** Pass
  `--extract-global-centerline 1`. It is worth it: the tree it returns has one
  cell per branch with radii, which finds vessel ends far better than reading
  them off the surface. `--cap-surface-cent 1` crashes inside SeqSeg's capping,
  so it is pinned off.
- **`--config-name` accepts an absolute path** with the `.yaml` suffix removed,
  which is how a per-case edited config works.
- **SeqSeg's `CenterlineId`** is a single column of branch labels, not one
  column per path as SimVascular writes it. `geometry/outlets.py::_polylines`
  prefers the line cells for this reason.
- **A raw SeqSeg surface is not clean.** The maintainer's CT gave 36
  disconnected pieces and non-manifold edges on a 2M-point surface.
- **Slice display must use image actors.** Cutting polygonal slices costs about
  1.1 s per slider step on a 512x64x512 scan; three `vtkImageActor`s with
  `SetDisplayExtent` cost 1 ms. Never call `grid.slice()` per interaction.
- **Seed picking cannot use VTK observers.** VTK gives the rotation style
  exclusive focus between press and release, so a release observer never fires.
  The click is caught with an event filter on the Qt render widget instead, and
  only a press and release within 4 px counts, so dragging still rotates.
- **VTK numbers polydata cells verts, then lines, then polys.** Indexing cells
  by row of the polygon array is wrong the moment a line cell exists, and
  cleaning creates one from a degenerate triangle. `clip.py::triangles_only`
  exists for this; a review found the crash it caused.

### How a cut works now

A cut is a box, not a plane: six half-spaces given to `vtkClipPolyData`, the way
SimVascular's box trim does it. It starts at the cut face, reaches `box_length`
along the outward normal, and is `box_width` wide, both in centimetres and both
per cut. Only wall inside the box can go, and of that only the piece connected
to the vessel end at the cut, so a neighbour crossing the box keeps its wall.
The box grows along the vessel until the piece it takes ends inside it, which
means a cut part way along a vessel trims it there. A cut that would take more
than half the model by area is refused by name. The rim is then projected onto
the cut plane so the cap is flat.

Numbers to compare against, on the tutorial aorta: preprocess 14 s, inlet
4.50 cm², seven outlets, smoothing moves the wall 0.25 mm. On the 2M-point CT:
smoothing 3 s, 20 cuts 87 s, 94% of the surface kept.

## What to do next

A design review of the clinician's path, image to results, found these. Roughly
in the order I would take them.

1. **Segmentation is a blind wait.** SeqSeg's output goes to a log file, so the
   window shows nothing for up to twenty minutes: no step counter, no estimate,
   no way to tell slow from hung. Stream the subprocess output into the run log
   (`Popen` and read lines), parse its step counter into a progress bar, and add
   a Stop button. There is no cancel anywhere in the application today.
2. **The Outlets review can be skipped.** Pressing Run on the Run step from a
   fresh image case segments and then clips with the automatic proposals,
   without showing them. Gate the clip on cuts the user has seen, or say so
   loudly on the Run step.
3. **Half the settings are invisible.** Only reachable by hand-editing
   `case.yaml`: smoothing passes and pass band, remesh and edge size, outlet
   back-off, assembly threshold, blood density and viscosity, cardiac cycles,
   tuning tolerance and iterations, 1D element size and segments per branch.
   Smoothing is the one the maintainer asked about by name.
4. **No way to inspect or repair the segmentation.** Nothing reports how many
   disconnected pieces or openings the surface has, or offers keep-largest-body,
   hole filling, or a smoothing preview. A Surface panel between Segment and
   Outlets is the natural home.
5. **A cut cannot be added where the detector found none.** Only proposed
   candidates can be ticked and moved. Trimming at a chosen level, say mid-arch,
   needs hand-edited YAML today.
6. **Nothing sanity-checks the model before a long run:** an implausible cap
   area, a flow split missing an outlet, a sample count under the CFL
   recommendation all pass silently.
7. **Redrawing is wasteful.** Every tick or nudge on the Outlets step rebuilds
   the whole wall actor, seconds per click on a 2M-point surface. Draw the wall
   once and update only the cut boxes.
8. **Nothing decimates the surface.** Full segmentation resolution is carried
   through cutting, centerlines and meshing. Around 200k points would speed the
   rest considerably; the remesh setting exists but is not exposed.
9. **Two steps are both numbered 1** (Outlets and Model), and the Model step
   still shows the surface-import form, including a units dropdown that is
   ignored for image cases.
10. **No report.** Results are a table, a folder of CSV files and a 3D view. One
    page with the model, per-outlet pressures and flows, the tuned boundary
    conditions and the waveform would finish the workflow.

## Known-but-unfixed, deeper in

- `geometry/centerline_tree.py::_blank_regions` can leave a one-node tract when
  two splits sit very close, which puts NaN into the reduced-order model. It
  needs a real fix in the blanking, not a patch.
- `case.py` records absolute output paths in the manifest, so moving a case
  directory re-runs everything.
- `io/solvers.py` picks the OneDSolver binary by lexical path order.
- Edits made in the window while a run is going are ignored: the worker holds
  its own `Case`.

## Working agreements

- The maintainer is cost-sensitive about spawning agents. One killed review
  still returned findings that were worth acting on, so a single focused review
  is fine; a fan-out of a dozen is not.
- Verify on real data before claiming something works. Both the tutorial aorta
  and `~/miros_cases/KDR12` are good tests, and they fail differently.
- Never patch files with a heredoc that opens them for writing before it can
  fail; it truncates them. Use the editing tools.
- `set -o pipefail` when a test command is piped, or a failure looks like a pass.
- Never let a smoke test write into `examples/aorta`; copy it to a temp
  directory first.
