# From an image

If you start from a CT or MR volume rather than a surface, MIROS runs
[SeqSeg](https://github.com/numisveinsson/SeqSeg) for you and opens the vessel ends of the
result. Needs the `[seg]` extra and a downloaded model; see [Install](install.md), step 5.

## The case

```yaml
segmentation:
  image: input/scan.nii.gz            # .nii(.gz) / .mha / .mhd / .nrrd / .vti / .vtk
  units: mm                           # units of the image coordinates
  model: aorta_ct                     # aorta_ct | aorta_mr | coronary_ct | path to an nnU-Net trainer folder
  config_name: ''                     # '' = the SeqSeg tracing config that suits the model; a name SeqSeg
                                      # ships, or your own file, e.g. input/seqseg_config.yaml
  max_steps: 1000                     # total tracing steps: how much of the tree is followed
  max_branches: 100                   # how many branches may be started
  max_steps_per_branch: 100           # how far along one branch before moving on
  assembly_threshold: 0.5             # probability at which the segmentation becomes the surface
  extract_centerline: true            # let SeqSeg centerline the tree; the cuts then come from it
  outlet_back_off: 2.5                # radii to walk back from each vessel end before cutting it open
  seeds:
    - {point: [x, y, z], direction: [x2, y2, z2], radius: 1.1}   # where to start, which way, lumen radius
model:
  surface: null                       # the surface comes from the segmentation
  smooth_iterations: 20               # a segmented wall carries the voxel grid; smooth it before cutting
```

A seed is a start point, a second point a little further along the vessel for the direction,
and the lumen radius there, all in image coordinates. The first seed is the inlet. In the window
they are two clicks on the slices each.

## What the segment stage does

`miros run` puts a `segment` stage in front of everything else. SeqSeg runs as a subprocess, so
torch never loads into MIROS, with its output streamed into the log and its step counter shown
as progress. From the result MIROS takes the smoothed surface and, from SeqSeg's centerline of
the tree, every vessel end with its radius. Each end becomes a proposed cut in
`work/outlets_proposed.json`, marked `use: true` where MIROS would cut and with a reason where
it would not.

**The cuts are yours to approve.** In the window they are the **Outlets** step; nothing is
clipped until you press *Apply cuts*. What you approve is written to `model.outlets` in
`case.yaml`, so the next run repeats it exactly; editing that list by hand does the same.

**A cut is a box, not a plane**, following SimVascular's box trim: six half-spaces given to
`vtkClipPolyData`. It starts at the cut face, reaches `box_length` along the outward normal and
is `box_width` wide, both in centimetres and both editable per cut. Only the wall inside that box
can go, so a cut can never take the body of the model, and of that wall only the piece connected
to the vessel end at the cut, so a neighbouring vessel crossing the box keeps its wall. The box
grows along the vessel until the piece it takes ends inside it. The rim is then put exactly on
the cut plane, so the cap is flat. A cut that would take more than half the model is reported by
name and skipped.

**Smoothing.** A surface out of segmentation carries the voxel grid, so `model.smooth_iterations`
(20 for an image case) runs a windowed sinc pass over the wall before the cuts, with
`model.smooth_pass_band` for how hard. These are SimVascular's own values; the wall moves about
a quarter of a millimetre on the tutorial aorta.

A VTK volume (`.vti`, `.vtk`) is converted once to `.mha` in `work/` for SeqSeg, keeping its
spacing, origin and orientation.

## The pretrained models

Published by the SeqSeg authors on Zenodo under CC-BY-4.0:
[aorta and femoral arteries, CT and MR](https://doi.org/10.5281/zenodo.15020477) (one 230 MB
archive gives `aorta_ct` and `aorta_mr`) and [coronary arteries, CT](https://doi.org/10.5281/zenodo.19547894)
(3 MB). `miros models download NAME` fetches and unpacks them into `~/.miros/models` (or
`MIROS_MODELS_DIR`); `miros models list` shows what is on disk. `segmentation.model` also accepts
a path to any nnU-Net trainer folder of your own.

## Cost and settings

A tracing step walks about one vessel radius and predicts one nnU-Net patch: about 1.4 s on an
RTX 4060 Ti, many times that on a CPU. An aortic arch is about 200 steps, root to iliacs about
800. `max_branches` is what stops SeqSeg wandering into every small vessel; keep it near the
number of outlets you want to model. The tracing config behind **all settings…** is SeqSeg's own
YAML; MIROS checks the chosen one for completeness before the run, because SeqSeg 2.1 ships
one (`global`) that is missing a key and dies a minute in.

Turn `extract_centerline` off for short test runs: on one 500³ CT, SeqSeg's centerline
extraction after a 12-step trace grew past 20 GB of memory and was killed by the system, while
the 800-step trace of the same image was fine. Without it the vessel ends are found on the
surface itself, which works too.
