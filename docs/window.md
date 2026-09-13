# The window

```bash
miros gui                     # start from an image or a surface
miros gui ~/cases/patient01   # open a case
miros setup ~/cases/patient01 # the same window opened on the Targets step
```

Needs the `[gui]` extra (`pip install -e ".[gui]"`) and a display. One window, the 3D model on
the left, the workflow as steps on the right. Everything a step does is also a command or an
edit to `case.yaml`; see [Commands](commands.md) and [The case file](case-file.md).

## Segment

Start here with a CT or MR volume (`.nii.gz`, `.mha`, `.nrrd`, `.vti`, `.vtk`). The image is
shown as three slices with sliders. Choose the pretrained model, download it if the page says
so, name a case folder and press **Create case from this image**. Then place seeds: two clicks on
a slice each, the start point and a point a little further along the vessel, with the lumen
radius from the box. Put the first seed where the inflow enters, for example the aortic root.
The tracing settings sit next to the model: total steps, branches, steps per branch, and
**all settings…** for the whole SeqSeg config, saved as a copy inside the case.

**Segment and open outlets** runs SeqSeg on the Run step with a step counter, then continues on
the Outlets step. See [From an image](segmentation.md) for what happens underneath.

## Outlets

Every vessel end found on the segmented surface is listed and drawn, solid where it will be cut
open and faint where it will not. Tick or untick an end, say which one is the inlet, rename it,
move a cut along its vessel, flip which side it discards, or change the box size. Nothing is
clipped until **Apply cuts and find the caps**. What you approve is written to `model.outlets`
in `case.yaml`, so the next run repeats it exactly.

## Model

Start here with a surface that is already open at the inlet and every outlet (`.vtp`, `.stl`,
`.ply`), in cm or mm. **Create case** finds the caps and writes `case.yaml`. **Open case** loads
an existing one.

## Inflow

One cardiac cycle on an embedded editor: drag the twenty control points, set the heart rate and
the peak flow, or load a two-column `.flow` file. The samples-per-cycle box shows a
recommendation from the CFL condition of the 1D model. **Save** writes `input/inflow.flow`.

## Targets

Click a cap in the 3D view or in the table to select it. Name the caps, mark the inlet, type each
outlet's share of the flow in percent (**equal** and **by area** fill them in), and give the
pressure target: systolic and diastolic, optionally mean, at the inlet or at a named outlet.
**Save** writes `case.yaml`.

## Run

**0D only** or **0D and 1D**, optionally projecting the 1D results onto a tetrahedral lumen. The
table shows each stage as fresh, stale or never run; **Run** executes only the stale ones,
**Re-run everything** all of them. The log streams live, including SeqSeg's own output; a
progress bar shows the segmentation step counter with the rate and a bound on the time left.
**Stop** ends the run: SeqSeg, OneDSolver and the tuner stop within seconds, another stage
finishes first. A stopped stage records nothing, so the next Run resumes there.

## Results

Per-outlet pressures and flows, the 0D plot, and the 1D pressure or flow painted onto the
vessels or the centerline with a time slider and a cycle-mean option.
