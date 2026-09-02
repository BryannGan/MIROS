"""
A Case is a directory with a case.yaml. It knows where every stage reads
and writes, and runs the stages that are out of date.

    case/
      case.yaml
      input/            what the user supplied (referenced from case.yaml)
      work/             intermediate files: surface, caps, centerlines, ROM inputs, rcrt.dat
      results/0D, /1D   solver outputs and extracted results
      .miros/manifest.json
"""
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .config import STAGES, CaseConfig, load_config
from .manifest import Manifest
from .ui import console


class StageError(RuntimeError):
    pass


class Case:
    def __init__(self, path):
        path = Path(path).resolve()
        if path.is_dir():
            self.dir, self.yaml = path, path / 'case.yaml'
        else:
            self.dir, self.yaml = path.parent, path
        self.config: CaseConfig = load_config(self.yaml)
        self.work = self.dir / 'work'
        self.results = self.dir / 'results'
        self.manifest = Manifest(self.dir / '.miros' / 'manifest.json')

    # ---- paths ---------------------------------------------------------
    def resolve(self, rel) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.dir / p)

    @property
    def surface_work(self) -> Path: return self.work / 'surface.vtp'
    @property
    def caps_json(self) -> Path: return self.work / 'caps.json'
    @property
    def boundary_dir(self) -> Path: return self.work / 'caps_and_wall'
    @property
    def centerlines(self) -> Path: return self.work / 'extracted_centerlines.vtp'
    @property
    def outlets_file(self) -> Path: return self.work / 'centerlines_outlets.dat'
    @property
    def inflow_work(self) -> Path: return self.work / 'inflow.flow'
    @property
    def rcrt(self) -> Path: return self.work / 'rcrt.dat'
    @property
    def zerod_json(self) -> Path: return self.work / '0D_solver_input.json'
    @property
    def zerod_tuned_json(self) -> Path: return self.work / '0D_solver_input_tuned.json'
    @property
    def tuning_report(self) -> Path: return self.work / 'tuning_report.json'
    @property
    def oned_input(self) -> Path: return self.work / '1D_solver_input.in'
    @property
    def oned_model(self) -> Path: return self.work / '1d_model.vtp'
    @property
    def mesh_complete_dir(self) -> Path: return self.work / 'mesh-complete'
    @property
    def results_0d(self) -> Path: return self.results / '0D'
    @property
    def results_1d(self) -> Path: return self.results / '1D'

    # ---- derived information ------------------------------------------
    def caps_info(self) -> dict:
        if not self.caps_json.exists():
            raise StageError("caps not computed yet: run the preprocess stage first")
        return json.loads(self.caps_json.read_text())

    def outlet_names(self) -> List[str]:
        if self.outlets_file.exists():
            return [l.strip() for l in self.outlets_file.read_text().splitlines() if l.strip()]
        return self.caps_info()['outlets']

    # ---- running -------------------------------------------------------
    def stages(self):
        from .stages import REGISTRY
        return REGISTRY

    def status(self) -> List[Tuple[str, str, str]]:
        """[(stage, 'fresh'|'stale'|'never'|'disabled'|'blocked', reason)]"""
        rows = []
        for st in self.stages():
            if not st.enabled(self):
                rows.append((st.name, 'disabled', st.disabled_reason(self)))
                continue
            try:
                inputs = st.inputs(self)
            except (FileNotFoundError, StageError) as e:
                rows.append((st.name, 'blocked', str(e)))
                continue
            state, reason = self.manifest.status(st.name, inputs)
            rows.append((st.name, state, reason))
        return rows

    def run(self, from_stage: Optional[str] = None, until: Optional[str] = None, force: bool = False,
            only: Optional[Sequence[str]] = None, progress=None) -> List[str]:
        """
        Run stale stages in order; returns the names of the stages that ran.
        progress(stage, event) is called with event in {'start', 'done', 'fresh', 'skipped'}.
        """
        notify = progress or (lambda *a: None)
        names = [s.name for s in self.stages()]
        for s in (from_stage, until):
            if s is not None and s not in names:
                raise ValueError("unknown stage %r; stages are %s" % (s, names))
        i_from = names.index(from_stage) if from_stage else None
        i_until = names.index(until) if until else len(names) - 1
        ran = []
        for i, st in enumerate(self.stages()):
            if i > i_until:
                break
            if only and st.name not in only:
                continue
            if not st.enabled(self):
                console.info("%-12s skipped (%s)" % (st.name, st.disabled_reason(self)))
                notify(st.name, 'skipped')
                continue
            try:
                inputs = st.inputs(self)
            except (FileNotFoundError, StageError) as e:
                raise StageError("%s cannot run: %s" % (st.name, e))
            state, reason = self.manifest.status(st.name, inputs)
            must = force or (i_from is not None and i >= i_from) or state != 'fresh'
            if not must:
                console.info("%-12s up to date (%s)" % (st.name, reason))
                notify(st.name, 'fresh')
                continue
            console.section("%s  (%s)" % (st.name, 'forced' if (force or i_from is not None) else reason))
            notify(st.name, 'start')
            t0 = time.time()
            outputs = st.run(self)
            self.manifest.record(st.name, inputs, [str(o) for o in outputs], extra={'seconds': round(time.time() - t0, 1)})
            console.ok("%s done in %.1f s" % (st.name, time.time() - t0))
            notify(st.name, 'done')
            ran.append(st.name)
        return ran
