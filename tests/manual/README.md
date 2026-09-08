# Manual checks

These run the real window and, in one case, real segmentation, so they do not
belong in `pytest`. They do run offscreen, which is how they were used:

```bash
export MIROS_TUTORIAL=~/miros_cases/seqseg_tutorial      # a case with case.yaml and work/
export MIROS_IMAGE=$MIROS_TUTORIAL/input/0110_0001.mha
QT_QPA_PLATFORM=offscreen python tests/manual/smoke_app3d.py
```

| Script | What it proves |
|---|---|
| `smoke_app3d.py` | the window on a surface case: caps, picking, 1D results, a run in the worker thread |
| `smoke_segment.py` | the Segment step end to end, including a real SeqSeg run (about 80 s on the tutorial) |
| `smoke_outlets.py` | the Outlets step: the cut list, editing a cut, applying it, choosing the inlet |
| `pick_test.py` | seed picking under real Qt mouse events: a click places a point, a drag rotates |
| `smoke_stop.py` | Stop during a real segmentation (SeqSeg killed, nothing left behind, the case resumes), then a short run to the end with the log and step counter streaming (about 3 minutes on KDR12) |
| `bench_slices.py` | what a slice view costs: polygonal slices against three image actors |

`smoke_app3d.py` needs only the repo's `examples/aorta`. `smoke_stop.py` needs
an image case with seeds (`MIROS_CASE`, default `~/miros_cases/KDR12`) and the
model it names. The others need a case that has already been segmented once,
because they start from its `work/` directory. See HANDOFF.md for the tutorial
data and seed they were written for.
