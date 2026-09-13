# Install

MIROS is a Python package. Around it sit three things it drives: the 0D solver **pysvzerod**,
the 1D solver **OneDSolver**, and the segmentation network **SeqSeg** with its pretrained weights.
Only MIROS itself is required; `miros doctor` tells you which of the rest are present.

| Piece | Needed for | Size | Where it comes from |
|---|---|---|---|
| MIROS | everything | small | this repository (PyPI release planned) |
| the window (`pyvistaqt`, `PySide6`) | `miros gui`, `setup`, `show`, `inflow edit` | 200 MB | PyPI, the `[gui]` extra |
| pysvzerod | the 0D simulation and the boundary-condition tuning | small, compiled | SimVascular's svZeroDSolver repository, built by pip |
| OneDSolver | the 1D simulation (`simulation.run_1d`) | 10 MB | SimVascular's installers on SimTK, or a CMake build |
| SeqSeg + torch + nnU-Net | segmenting an image | 2 GB | PyPI, the `[seg]` extra |
| SeqSeg weights | segmenting an image | 3 to 230 MB per model | Zenodo, through `miros models download` |

The same five steps on every operating system; the per-OS sheets at the end put each one on a
single page you can paste.

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

## 3. The 0D solver: pysvzerod

svZeroDSolver ships no wheels, so pip builds it. CMake and Ninja are fetched by pip; the one
thing you provide is a C++ compiler.

| OS | The compiler |
|---|---|
| Ubuntu / Debian | `sudo apt install build-essential git` |
| Fedora / RHEL | `sudo dnf groupinstall "Development Tools"` |
| macOS | `xcode-select --install` (the command line tools) |
| Windows | [Visual Studio Build Tools 2022](https://visualstudio.microsoft.com/visual-cpp-build-tools/), workload "Desktop development with C++"; then open a new terminal |

Then, in the same environment as MIROS:

```bash
pip install git+https://github.com/simvascular/svZeroDSolver.git
python -c "import pysvzerod; print('0D solver ok')"
```

The build takes a few minutes. Without it, `miros run` stops at the `tune` stage and says so.

## 4. The 1D solver: OneDSolver

Optional: set `simulation.run_1d: false` in `case.yaml` and the pipeline ends with the 0D
results. Otherwise, either install SimVascular's package or build it.

**Installers** are on [SimTK](https://simtk.org/frs/?group_id=188) (no account needed):

| OS | Package | Installs to | Found by MIROS |
|---|---|---|---|
| Ubuntu 24 / 25 | `oneD-solver-Ubuntu-24-2025.07.02.deb`, `oneD-solver-Ubuntu-25-2026.01.16.deb` | `/usr/local/sv/oneDSolver/<date>/bin/OneDSolver` | automatically |
| macOS (Apple silicon) | `oneD-solver-MacOS-Ventura-arm-2025.06.26.pkg` | `/usr/local/sv/oneDSolver/<date>/bin/OneDSolver` | automatically |
| Windows | `svOneDSolver-Windows-2022-07.msi` (older) | `C:\Program Files\SimVascular\svOneDSolver\<date>\` | automatically |

```bash
sudo dpkg -i oneD-solver-Ubuntu-24-2025.07.02.deb      # Ubuntu; macOS: open the .pkg; Windows: run the .msi
```

**From source** on any OS, with CMake 3.18 or newer and the compiler from step 3:

```bash
git clone https://github.com/SimVascular/svOneDSolver.git
cmake -S svOneDSolver -B svOneDSolver/build -DCMAKE_BUILD_TYPE=Release -DENABLE_UNIT_TEST=OFF
cmake --build svOneDSolver/build --config Release --parallel
```

The executable is `svOneDSolver/build/bin/OneDSolver` (`build\bin\Release\OneDSolver.exe` with
Visual Studio). Tell MIROS where it is in one of three ways: put it on your `PATH`, set the
environment variable `MIROS_ONEDSOLVER` to its path, or set `solvers.onedsolver` in `case.yaml`.

## 5. SeqSeg, for segmenting images

The `[seg]` or `[all]` extra installs SeqSeg, nnU-Net and torch. Torch is the part that decides
whether a GPU is used:

| OS | What pip installs by default | For an NVIDIA GPU |
|---|---|---|
| Linux | torch with CUDA | nothing more to do |
| Windows | torch for the CPU only | `pip install torch --index-url https://download.pytorch.org/whl/cu128` after the extra |
| macOS | torch for the CPU and Apple's GPU | CUDA does not exist on macOS |

Tracing runs on the CPU too, only much slower: a step is about 1.4 s on an RTX 4060 Ti, and a
whole aorta is 300 to 800 steps.

Then the pretrained weights, published by the SeqSeg authors on Zenodo under CC-BY-4.0:

```bash
miros models download aorta_ct        # aorta and femoral arteries, CT (230 MB, includes aorta_mr)
miros models download coronary_ct     # coronary arteries, CT (3 MB)
miros models list
```

They go to `~/.miros/models`; set `MIROS_MODELS_DIR` to put them elsewhere.

## 6. Check

```bash
miros doctor
```

With everything present it ends like this; a `MISSING` line names what to install, and the
1D and segmentation lines are the ones that may legitimately stay absent:

```
  pysvzerod   │ ok      │         │ 0D solver
  seqseg      │ ok      │         │ upstream segmentation
  OK OneDSolver: /usr/local/sv/oneDSolver/2025-07-02/bin/OneDSolver
  SeqSeg models in /home/you/.miros/models:
    aorta_ct     ready    Aorta and femoral arteries, CT (Vascular Model Repository)
    aorta_mr     ready    Aorta and femoral arteries, MR (Vascular Model Repository)
    coronary_ct  absent   Coronary arteries, CT angiography
  display for interactive editors: yes
```

Then prove it on the example, which needs both solvers:

```bash
miros run examples/aorta
```

## Per-OS sheets

Each block is the whole install, top to bottom, on a fresh machine.

### Ubuntu / Debian

```bash
sudo apt install -y python3 python3-venv build-essential git cmake
git clone https://github.com/BryannGan/MIROS.git && cd MIROS
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
pip install git+https://github.com/simvascular/svZeroDSolver.git
# OneDSolver: download oneD-solver-Ubuntu-24-2025.07.02.deb from https://simtk.org/frs/?group_id=188, then
sudo dpkg -i oneD-solver-Ubuntu-24-2025.07.02.deb
miros models download aorta_ct
miros doctor
miros run examples/aorta
```

Other distributions: replace the first line with your compiler and Python packages, and build
OneDSolver from source (step 4) instead of the `.deb`.

### macOS

```bash
xcode-select --install
git clone https://github.com/BryannGan/MIROS.git && cd MIROS
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
pip install git+https://github.com/simvascular/svZeroDSolver.git
# OneDSolver: download oneD-solver-MacOS-Ventura-arm-2025.06.26.pkg from https://simtk.org/frs/?group_id=188 and open it
miros models download aorta_ct
miros doctor
miros run examples/aorta
```

On an Intel Mac build OneDSolver from source (step 4).

### Windows (PowerShell)

Install [Python 3.12](https://www.python.org/downloads/windows/) with "Add python.exe to PATH",
[Git](https://git-scm.com/download/win), and the
[Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) with the
"Desktop development with C++" workload. Then, in a new PowerShell:

```powershell
git clone https://github.com/BryannGan/MIROS.git; cd MIROS
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e ".[all]"
pip install torch --index-url https://download.pytorch.org/whl/cu128     # only with an NVIDIA GPU
pip install git+https://github.com/simvascular/svZeroDSolver.git
# OneDSolver: run svOneDSolver-Windows-2022-07.msi from https://simtk.org/frs/?group_id=188, or build it (step 4)
miros models download aorta_ct
miros doctor
miros run examples/aorta
```

If `Activate.ps1` is refused, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

## Environment variables

| Variable | Meaning |
|---|---|
| `MIROS_ONEDSOLVER` | path to the OneDSolver executable, when it is not on `PATH` or in a known place |
| `MIROS_MODELS_DIR` | where the SeqSeg weights live (default `~/.miros/models`) |
| `QT_QPA_PLATFORM=offscreen` | run the window's tests without a display |

## Updating

```bash
cd MIROS && git pull && pip install -e ".[all]"
```

pysvzerod and OneDSolver do not need reinstalling when MIROS updates.
