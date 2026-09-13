# Development

```bash
pip install -e ".[dev]"                                 # the window plus pytest
python -m pytest tests/unit -q                          # a few seconds, no solvers needed
QT_QPA_PLATFORM=offscreen python -m pytest tests -q     # unit and integration, about 90 s with both solvers
```

The integration tests that solve skip without `pysvzerod` or `OneDSolver`. `tests/manual/` holds
checks that need a window or a real segmentation and are run by hand; see its README.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request: Ubuntu, macOS
and Windows on Python 3.10 and 3.12 (3.11 on Ubuntu), each installing `.[dev]` and running the
unit tests with the window offscreen, the integration tests, and the command line from the
example surface to the 0D model. The solvers are not installed on the runners, so the 0D and 1D
solves are covered only by the local suite.

## Validation

`tests/integration/test_centerlines_vs_simvascular.py` gates the centerline backend against
SimVascular's output on the example (`examples/aorta/reference`): the same branches and
junctions, path lengths within 3 %, end-of-branch areas equal to the cap areas, and a 0D model
that reproduces SimVascular's flow splits within one percentage point with identical boundary
conditions (measured: 0.4).

## Layout and conventions

[CLAUDE.md](../CLAUDE.md) is the one-page map of the package and its rules;
[HANDOFF.md](../HANDOFF.md) the long version: every stage, the geometry, the facts about SeqSeg
that were expensive to learn, the known defects, and the backlog. The rules that matter most:

- No SimVascular, vmtk or conda-only dependencies; everything installs with pip on all three
  operating systems, Python 3.10 to 3.12.
- Outlet caps map to 0D vessels only through the 0D JSON, never by name or sort order.
- Units: geometry in cm, flow in mL/s, pressure in dyn/cm² internally and mmHg at every
  user-facing point.
- Every file format has one reader and writer in `miros/io`; every subprocess goes through
  `miros/io/process.py`.
- Text files are read as UTF-8 and written with `\n`.

## Adding a stage

Write `inputs(case)`, `outputs(case)`, `run(case)` and optionally `enabled(case)` in a module
under `miros/stages/`, and register it in `miros/stages/__init__.py` in pipeline order. The
manifest hashes what `inputs` returns, so the stage is re-run exactly when those change.
