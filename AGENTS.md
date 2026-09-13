# For coding agents

MIROS turns a CT/MR image or a vessel surface into 0D and 1D blood-flow simulations. Python
package, one command line (`miros`), one Qt window, one case file (`case.yaml`), ten stages run
by a manifest that re-runs only what changed.

## Set up and verify

1. Python 3.10 to 3.12, then `pip install -e ".[dev]"` (window plus pytest) or `".[all]"`.
2. `miros install all` fetches the 0D solver (pysvzerod), the 1D solver (OneDSolver, into
   `~/.miros/bin`) and SeqSeg with its weights; each is also a command of its own.
   [docs/install.md](docs/install.md) has every step by hand, per OS.
3. `miros doctor` reports what is present and what command completes the install.
   `miros run examples/aorta` proves the whole pipeline.

## Test

```bash
python -m pytest tests/unit -q                          # seconds; run before every commit
QT_QPA_PLATFORM=offscreen python -m pytest tests -q     # with the integration tests, ~90 s with the solvers
```

Tests never write into `examples/`; copy the example to a temporary directory. Verify a change on
real data before claiming it works; the example aorta and a real CT fail differently.

## Where things are

- [CLAUDE.md](CLAUDE.md): the one-page map, entry points, conventions.
- [HANDOFF.md](HANDOFF.md): every stage and what it writes, the geometry algorithms, the case
  file's traps, the window's threading and VTK rules, the SeqSeg facts, the known defects, and
  the prioritised backlog. Read it before touching the pipeline; do not re-derive it.
- `miros/stages/`: one module per stage; `miros/geometry/`: caps, centerlines, cuts, smoothing;
  `miros/io/`: every file format and the subprocess runner; `miros/ui/`: the window.

## Rules that are not negotiable

- No SimVascular, vmtk or conda-only dependencies; pip on Linux, macOS and Windows.
- Outlet caps map to 0D vessels only through the 0D JSON (`io/zerod.VesselMap`).
- Geometry in cm, flow in mL/s, pressure in mmHg at every user-facing point.
- File formats are read and written only in `miros/io`; subprocesses only through
  `miros/io/process.run_logged`, which streams, logs and can be stopped.
- Text files: `encoding='utf-8'` on reads, `newline='\n'` on writes.
- Never open a window off the main thread; never patch a file with a heredoc that truncates it
  before it can fail.
