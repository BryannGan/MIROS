# Install

MIROS is a Python package. Around it sit three things it drives: the 0D solver **pysvzerod**,
the 1D solver **OneDSolver**, and the segmentation network **SeqSeg** with its pretrained weights.
Only MIROS itself is required; `miros doctor` tells you which of the rest are present, and
`miros install` fetches them.

| Piece | Needed for | Size | Where it comes from |
|---|---|---|---|
| MIROS | everything | small | this repository (PyPI release planned) |
| the window (`pyvistaqt`, `PySide6`) | `miros gui`, `setup`, `show`, `inflow edit` | 200 MB | PyPI, the `[gui]` extra |
| pysvzerod | the 0D simulation and the boundary-condition tuning | small, compiled | a prebuilt wheel from this repository's `solvers` release, else built from SimVascular's svZeroDSolver by pip |
| OneDSolver | the 1D simulation (`simulation.run_1d`) | 10 MB | a prebuilt executable from the `solvers` release, or SimVascular's installer, or a CMake build |
| SeqSeg + torch + nnU-Net | segmenting an image | 2 GB | PyPI |
| SeqSeg weights | segmenting an image | 3 to 230 MB per model | Zenodo, through `miros models download` |

The same steps on every operating system; the per-OS sheets at the end put each on one page you
can paste.

## 1. Python 3.10, 3.11 or 3.12

Any of them, in a virtual environment of your choosing:

```bash
python -m venv .venv
source .venv/bin/activate          # Linux, macOS
.venv\Scripts\Activate.ps1         # Windows PowerShell
```

or `conda create -n MIROS python=3.12 && conda activate MIROS`. Python 3.9 is not supported: its
last VTK and pyvista wheels crash under Qt.

## 2. MIROS

```bash
git clone https://github.com/BryannGan/MIROS.git
cd MIROS
pip install -e ".[all]"
```

`[all]` is the window plus segmentation. Pick less if you want less:

| Install | Gives you |
|---|---|
| `pip install -e .` | the command line: `init`, `run`, `status` |
| `pip install -e ".[gui]"` | plus the window |
| `pip install -e ".[seg]"` | plus SeqSeg, nnU-Net and torch |
| `pip install -e ".[all]"` | both |
| `pip install -e ".[dev]"` | the window plus pytest, for working on the code |

## 3. The solvers and SeqSeg

```bash
miros install all
```

That is the three commands below in one go. Each can be run alone, and each says what it did.

### `miros install pysvzerod`, the 0D solver

svZeroDSolver publishes no wheels, so MIROS keeps prebuilt ones for Linux, macOS (Apple silicon)
and Windows on Python 3.10 to 3.12 in the [`solvers` release](https://github.com/BryannGan/MIROS/releases/tag/solvers),
compiled from SimVascular's source by [a workflow in this repository](../.github/workflows/build-solvers.yml).
The command takes the one that fits your machine. When none does, it builds from source, which
needs a C++ compiler; CMake and Ninja are fetched by pip:

| OS | The compiler |
|---|---|
| Ubuntu / Debian | `sudo apt install build-essential git` |
| Fedora / RHEL | `sudo dnf groupinstall "Development Tools"` |
| macOS | `xcode-select --install` |
| Windows | [Visual Studio Build Tools 2022](https://visualstudio.microsoft.com/visual-cpp-build-tools/), workload "Desktop development with C++"; then open a new terminal |

By hand, the source build is `pip install git+https://github.com/simvascular/svZeroDSolver.git`.

### `miros install onedsolver`, the 1D solver

Downloads the prebuilt `OneDSolver` for your OS from the same release into `~/.miros/bin`, where
MIROS looks first. The 1D simulation is optional: `simulation.run_1d: false` in `case.yaml` ends
the pipeline with the 0D results, and then this step can be skipped.

By hand, either of these also works, and MIROS finds the result on its own:

- SimVascular's installers on [SimTK](https://simtk.org/frs/?group_id=188) (no account needed):
  `oneD-solver-Ubuntu-24-2025.07.02.deb` and `oneD-solver-Ubuntu-25-2026.01.16.deb`
  (`sudo dpkg -i …`), `oneD-solver-MacOS-Ventura-arm-2025.06.26.pkg`, and an older
  `svOneDSolver-Windows-2022-07.msi`. They install under `/usr/local/sv/oneDSolver/<date>/bin`
  or `C:\Program Files\SimVascular\svOneDSolver`.
- A build from source, with CMake 3.18 and the compiler above:

  ```bash
  git clone https://github.com/SimVascular/svOneDSolver.git
  cmake -S svOneDSolver -B svOneDSolver/build -DCMAKE_BUILD_TYPE=Release -DENABLE_UNIT_TEST=OFF
  cmake --build svOneDSolver/build --config Release --parallel
  ```

  The executable is `svOneDSolver/build/bin/OneDSolver` (`build\bin\Release\OneDSolver.exe` with
  Visual Studio). Put it on `PATH`, or set `MIROS_ONEDSOLVER` to its path, or set
  `solvers.onedsolver` in `case.yaml`.

### `miros install seqseg`, for segmenting images

Installs SeqSeg, nnU-Net and SimpleITK, then downloads the `aorta_ct` weights (230 MB, which
also gives `aorta_mr`; `--no-models` skips them, `miros models download coronary_ct` adds the
3 MB coronary model). Torch is the part that decides whether a GPU is used:

| OS | `miros install seqseg` does | Options |
|---|---|---|
| Linux | torch with CUDA when `nvidia-smi` is found, else the default torch (which also has CUDA) | `--gpu`, `--cpu` |
| Windows | torch with CUDA 12.8 from PyTorch's index when `nvidia-smi` is found; the default torch is CPU-only | `--gpu`, `--cpu` |
| macOS | the default torch, which uses Apple silicon through MPS; CUDA does not exist on macOS | |

Tracing runs on the CPU too, only much slower: a step is about 1.4 s on an RTX 4060 Ti, and a
whole aorta is 300 to 800 steps. The weights go to `~/.miros/models`; set `MIROS_MODELS_DIR` to
put them elsewhere.

## 4. Check

```bash
miros doctor
```

With everything present it ends with `everything is in place`. Otherwise it ends with the
`miros install` commands that would complete the install, like this:

```
  pysvzerod   │ MISSING │         │ 0D solver
  WARNING OneDSolver not found; 1D simulation is unavailable until it is. Get it with: miros install onedsolver ...
  SeqSeg models in /home/you/.miros/models:
    aorta_ct     absent   Aorta and femoral arteries, CT (Vascular Model Repository)
    ...
  to complete the install
  miros install pysvzerod      the 0D solver (tuning and sim_0d need it)
  miros install onedsolver     the 1D solver, or set simulation.run_1d: false
  miros models download aorta_ct   the weights for segmenting
  or everything at once: miros install all
```

Then prove it on the example, which needs both solvers:

```bash
miros run examples/aorta
```

## Per-OS sheets

Each block is the whole install, top to bottom, on a fresh machine.

### Ubuntu / Debian

```bash
sudo apt install -y python3 python3-venv git
git clone https://github.com/BryannGan/MIROS.git && cd MIROS
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
miros install all
miros doctor
miros run examples/aorta
```

Other distributions: use their Python and git packages. Prebuilt pieces cover x86_64; on another
architecture `miros install` builds pysvzerod from source (it needs `gcc`, `g++`) and OneDSolver
comes from a source build (step 3).

### macOS

```bash
git clone https://github.com/BryannGan/MIROS.git && cd MIROS
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
miros install all
miros doctor
miros run examples/aorta
```

The prebuilt pieces are for Apple silicon. On an Intel Mac, `xcode-select --install` first;
pysvzerod then builds from source and OneDSolver comes from SimTK's `.pkg` or a source build.

### Windows (PowerShell)

Install [Python 3.12](https://www.python.org/downloads/windows/) with "Add python.exe to PATH"
and [Git](https://git-scm.com/download/win). Then:

```powershell
git clone https://github.com/BryannGan/MIROS.git; cd MIROS
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e ".[all]"
miros install all
miros doctor
miros run examples\aorta
```

If `Activate.ps1` is refused, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.
The Visual Studio Build Tools are needed only if `miros install pysvzerod` has to build from
source, which it says when it does.

## Environment variables

| Variable | Meaning |
|---|---|
| `MIROS_HOME` | where `miros install` and `miros models` put things (default `~/.miros`: `bin/`, `models/`, `wheels/`) |
| `MIROS_MODELS_DIR` | the SeqSeg weights alone (default `MIROS_HOME/models`) |
| `MIROS_ONEDSOLVER` | path to an OneDSolver executable, when it is not in `MIROS_HOME/bin`, on `PATH` or in a known place |
| `QT_QPA_PLATFORM=offscreen` | run the window's tests without a display |

## Updating

```bash
cd MIROS && git pull && pip install -e ".[all]"
```

The solvers and SeqSeg do not need reinstalling when MIROS updates. `miros install` again picks
up newer prebuilt pieces when the `solvers` release is rebuilt.
