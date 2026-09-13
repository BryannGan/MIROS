# MIROS

**Medical Image to Patient-Specific Reduced-Order Hemodynamic Model Simulation in Minutes**

[![ci](https://github.com/BryannGan/MIROS/actions/workflows/ci.yml/badge.svg)](https://github.com/BryannGan/MIROS/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)
![os](https://img.shields.io/badge/os-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)
![license](https://img.shields.io/badge/license-MIT-green)

MIROS takes a CT or MR angiogram, or a vessel surface you already have, and turns it into
patient-specific 0D and 1D blood-flow simulations: segmentation with
[SeqSeg](https://github.com/numisveinsson/SeqSeg), centerlines, the reduced-order models, outlet
boundary conditions tuned to the flow split and pressures you ask for, the
[svZeroDSolver](https://github.com/simvascular/svZeroDSolver) and
[svOneDSolver](https://github.com/SimVascular/svOneDSolver) runs, and the results in mmHg.
One window or one command, every input in one file, and only what changed is recomputed.
No SimVascular installation is needed.

*(Manuscript in preparation.)*

```
image ──segment──▶ surface ──preprocess──▶ caps ──rom_model──▶ centerlines, 0D model
                                                                      │
        results/0D, results/1D ◀──extract──  sim_0d, sim_1d  ◀──tune──┘  RCR boundary conditions
```

## Install

Python 3.10 to 3.12 on Linux, macOS or Windows.

```bash
git clone https://github.com/BryannGan/MIROS.git && cd MIROS
python -m venv .venv && source .venv/bin/activate      # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[all]"                                 # MIROS, the window, SeqSeg (pulls torch, about 2 GB)
miros install all                                       # the two SimVascular solvers and the SeqSeg weights
miros doctor                                            # what is there, what is missing, and how to get it
```

| `miros install …` | Gets | From |
|---|---|---|
| `pysvzerod` | the 0D solver ([svZeroDSolver](https://github.com/simvascular/svZeroDSolver)), for the tuning and `sim_0d` | a prebuilt wheel in this repository's [`solvers` release](https://github.com/BryannGan/MIROS/releases/tag/solvers), else a source build |
| `onedsolver` | the 1D solver ([svOneDSolver](https://github.com/SimVascular/svOneDSolver)), for `sim_1d`, optional | a prebuilt executable in the same release, into `~/.miros/bin` |
| `seqseg` | [SeqSeg](https://github.com/numisveinsson/SeqSeg) with a torch for your GPU, and the `aorta_ct` weights | PyPI and Zenodo |

**[The install guide](https://github.com/BryannGan/MIROS/blob/main/docs/install.md)** has each step by hand as well, per operating system,
and what `miros doctor` prints when everything is in place.

## Try it

```bash
miros run examples/aorta
```

The bundled aortic arch goes from surface to tuned 0D and 1D results in about two minutes.
Results land in `examples/aorta/results/0D` and `results/1D`. Run it again and nothing happens:
every stage records what it read, and only stale stages re-run.

## Your own case

**In the window**, from an image or a surface:

```bash
miros gui
```

Seven steps, the 3D model always on the left: **Segment** (image, seeds, SeqSeg) →
**Outlets** (approve the cuts that open the vessel ends) → **Model** (or start here from a clipped
surface) → **Inflow** (draw or load one cardiac cycle) → **Targets** (name the caps, flow shares,
pressure) → **Run** (live log, progress, Stop) → **Results**.

**On the command line**, from a clipped surface:

```bash
miros init ~/cases/patient01 --surface surface.vtp --inflow inflow.flow   # writes a commented case.yaml
miros setup ~/cases/patient01                                             # or edit case.yaml: flow split, pressure targets
miros run ~/cases/patient01
```

## Documentation

| Page | What is in it |
|---|---|
| [Install](https://github.com/BryannGan/MIROS/blob/main/docs/install.md) | every dependency, per operating system, and how to check them |
| [The window](https://github.com/BryannGan/MIROS/blob/main/docs/window.md) | the seven steps of `miros gui` |
| [Commands](https://github.com/BryannGan/MIROS/blob/main/docs/commands.md) | `miros doctor / init / run / status / models / gui / setup / show / inflow`, the stages, the library |
| [The case file](https://github.com/BryannGan/MIROS/blob/main/docs/case-file.md) | every option in `case.yaml`, with the full template |
| [From an image](https://github.com/BryannGan/MIROS/blob/main/docs/segmentation.md) | SeqSeg, seeds, the pretrained models, how the vessel ends are opened |
| [Boundary-condition tuning](https://github.com/BryannGan/MIROS/blob/main/docs/tuning.md) | how the RCR values are found, and which targets are reachable |
| [Troubleshooting](https://github.com/BryannGan/MIROS/blob/main/docs/troubleshooting.md) | the messages you may see and what they mean |
| [Development](https://github.com/BryannGan/MIROS/blob/main/docs/development.md) | tests, continuous integration, validation against SimVascular, layout |

Working on the code with an AI agent? [AGENTS.md](https://github.com/BryannGan/MIROS/blob/main/AGENTS.md) is written for it.

## Citation

MIROS builds on SimVascular, svZeroDSolver, svOneDSolver and SeqSeg. Please cite them with it
(see [CITATION.cff](https://github.com/BryannGan/MIROS/blob/main/CITATION.cff)):

- Updegrove A. et al., *SimVascular: An Open Source Pipeline for Cardiovascular Simulation*, Ann Biomed Eng 2017.
- Pfaller M.R. et al., *Automated generation of 0D and 1D reduced-order models of patient-specific blood flow*, Int J Numer Meth Biomed Eng 2022.
- Sveinsson Cepero N. & Shadden S.C., *SeqSeg: Learning Local Segments for Automatic Vascular Model Construction*, Ann Biomed Eng 2024. https://doi.org/10.1007/s10439-024-03611-z

## License

MIT (see [LICENSE](https://github.com/BryannGan/MIROS/blob/main/LICENSE)). The vendored SimVascular modules under `miros/rom` and
`miros/rom_extract` keep their own permissive license, reproduced in every file.
