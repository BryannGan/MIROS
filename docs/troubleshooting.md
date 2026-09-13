# Troubleshooting

`miros doctor` first. It lists every Python package, finds `OneDSolver`, and shows the downloaded
models.

| You see | It means | Do |
|---|---|---|
| `pysvzerod │ MISSING` | the 0D solver is not installed | `miros install pysvzerod` |
| `pysvzerod did not build` | no prebuilt wheel fits this machine and the source build failed | install a C++ compiler ([Install](install.md), step 3) and run it again |
| `DLL load failed while importing pysvzerod` (Windows) | a source build of pysvzerod; its extension cannot find a DLL | use a Python version with a prebuilt wheel (3.10 to 3.12) and `miros install pysvzerod` again |
| `WARNING OneDSolver not found` | no 1D solver in `~/.miros/bin`, on `PATH` or in the usual places | `miros install onedsolver`, or `simulation.run_1d: false` |
| `no prebuilt OneDSolver for …` | your OS or architecture has no prebuilt executable | SimVascular's installer or a source build, [Install](install.md) step 3 |
| `cannot list the prebuilt solvers` | no network, or GitHub's API rate limit | try later; the by-hand routes in [Install](install.md) do not need it |
| `the MIROS window needs the GUI extra` | `pyvistaqt` or `PySide6` is absent | `pip install -e ".[gui]"` |
| `model 'aorta_ct' is not downloaded yet` | no weights | `miros models download aorta_ct` |
| `segmentation.seeds is empty` | a case created from an image has no seeds yet | place them on the Segment step, or add `{point, direction, radius}` entries |
| `the SeqSeg config 'global' is missing ADD_RADIUS` | SeqSeg 2.1 ships an incomplete config | leave `config_name` empty, or pick `global_aorta` / `global_coro` |
| `SeqSeg failed (exit -9)` | the system killed SeqSeg, almost always for memory | shorter trace, or `extract_centerline: false`; see `dmesg` on Linux |
| `Surface has no boundary loops` | the surface is closed | open it: cuts under `model.outlets`, the Outlets step, or clip it elsewhere |
| `outlet … is not reachable from the inlet through the lumen` | a gap in the surface, or two vessels that are not actually joined | look at it in ParaView or the window |
| `flow_split names … are not outlets` | the names in `case.yaml` do not match the caps | `miros show caps DIR` lists them |
| `flow_split is missing outlet(s)` | every outlet needs a share | add them; they must sum to 100 |
| `outlet planes could not be matched` | (old versions) more cuts than caps | update MIROS; caps and cuts are now matched by proximity |
| `the run failed; see the log` (window) | a stage raised | the Run step's log has the traceback; the earlier stages stay fresh |
| `run stopped` | you pressed Stop, or Ctrl-C | Run again resumes at that stage |
| the window is wider than the screen | an old version | update MIROS |
| `QOpenGLWidget is not supported on this platform` | Qt has no GL context, for example over a remote desktop | the 3D view needs a display with OpenGL; the command line does not |

Two limits of the tuner are reported rather than hidden; see [Tuning](tuning.md): the inlet
pulse pressure has a floor set by the waveform and the vessels, and outlet mean pressures are
nearly identical by physics.

A stage that fails leaves the earlier stages fresh: fix the input and `miros run` again, and only
the failed stage and its dependants run. `miros status DIR` shows why each stage is stale.
