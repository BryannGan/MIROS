"""
segment: image -> vessel surface with SeqSeg (optional first stage).

Runs `seqseg run single` in a subprocess (SeqSeg, nnU-Net and torch stay
out of this process), collects the smoothed surface and the tracked
centerline, and proposes outlet cut planes from that centerline so the
closed SeqSeg surface can be opened by the preprocess stage.

Outputs in work/:
    seqseg_surface.vtp        closed surface from SeqSeg (image coordinates)
    seqseg_centerline.vtp     tracked centerline with radii
    outlets_proposed.json     cut planes (origin, normal, radius, inlet flag)
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from ..config import ConfigError
from ..geometry.caps import read_polydata
from ..geometry.outlets import propose_from_closed_surface, propose_outlet_planes
from ..io.process import run_logged, strip_ansi
from ..manifest import file_hash, value_hash
from ..models import MODELS, find_model_folder
from ..ui import console


def enabled(case):
    return bool(case.config.segmentation.image)


def disabled_reason(case):
    return 'segmentation.image is not set (starting from model.surface)'


def _model_folder(case) -> Path:
    sg = case.config.segmentation
    folder = find_model_folder(sg.model)
    if folder is None:
        if sg.model in MODELS:
            raise ConfigError("model '%s' is not downloaded yet: run `miros models download %s`" % (sg.model, sg.model))
        raise ConfigError("segmentation.model: no nnU-Net trainer folder at %s" % sg.model)
    return folder


def inputs(case):
    sg = case.config.segmentation
    return {'image': file_hash(case.resolve(sg.image)), 'segmentation': value_hash(case.config.section('segmentation')),
            'model': str(_model_folder(case))}


def outputs(case):
    return [case.work / 'seqseg_surface.vtp', case.work / 'outlets_proposed.json']


def _scale(image_units: str, model_units: str) -> float:
    return {('mm', 'cm'): 0.1, ('cm', 'mm'): 10.0}.get((image_units, model_units), 1.0)


def _seqseg_configs():
    """{name: path} of the tracing configs shipped with the installed SeqSeg."""
    try:
        import seqseg.config as C
    except ImportError:
        return {}
    return {p.stem: p for d in getattr(C, '__path__', []) for p in sorted(Path(d).glob('*.yaml'))}


def _config_name(case) -> str:
    """
    The SeqSeg tracing config, as SeqSeg's --config-name wants it.

    It can be one of the configs SeqSeg ships (by name), or a YAML file of
    your own inside the case, e.g. `input/seqseg_config.yaml`, which the
    GUI writes when the settings are edited. Either way the settings are
    checked here: some configs shipped upstream are incomplete (SeqSeg
    2.1's `global` has no ADD_RADIUS and dies mid-trace), and finding that
    out an hour into a run is no use to anyone.
    """
    sg = case.config.segmentation
    name = sg.config_name or MODELS.get(sg.model, {}).get('config') or 'global_default'
    available = _seqseg_configs()
    own = case.resolve(name) if ('/' in str(name) or str(name).endswith('.yaml')) else None
    if own is not None:
        if not own.exists():
            raise ConfigError("segmentation.config_name: no such file: %s" % own)
        available = dict(available)
        available[str(own.with_suffix(''))] = own
        name = str(own.with_suffix(''))              # SeqSeg accepts an absolute path without the suffix
    if not available:
        return name                                  # SeqSeg not importable here; let the subprocess complain
    if name not in available:
        raise ConfigError("segmentation.config_name %r is not a SeqSeg config; available: %s"
                          % (name, ', '.join(sorted(available))))
    import yaml
    keys = {}
    for n, path in available.items():
        try:
            keys[n] = set(yaml.safe_load(path.read_text(encoding='utf-8', errors='replace')) or {})
        except Exception:                                # noqa: BLE001 - unreadable config
            keys[n] = set()
    complete = max((k for n, k in keys.items() if n != name), key=len, default=set())   # a full config's settings
    missing = sorted(complete - keys.get(name, set()))
    if missing:
        good = sorted(n for n, k in keys.items() if not (complete - k))
        raise ConfigError("the SeqSeg config %r is missing %s, so tracing would stop part way through. "
                          "Set segmentation.config_name to one of: %s" % (name, ', '.join(missing), ', '.join(good)))
    return name


def _steps_in_name(p: Path) -> int:
    m = re.search(r'_(\d+)_steps', p.name)
    return int(m.group(1)) if m else -1


# ---- watching SeqSeg while it runs -------------------------------------------
#
# What SeqSeg sends down the pipe is nnU-Net's progress bar for every
# prediction, a few warnings, and its own opening and closing lines. Its
# tracing log, with the step counter, goes elsewhere: unless DEBUG is on (and
# DEBUG stops in pdb at DEBUG_STEP, so it cannot be turned on) it points
# sys.stdout at out.txt in its scratch directory, next to work/seqseg. The
# counter is read from that file as it grows. Python buffers that file, so
# it advances every few steps rather than every step.

_TQDM = re.compile(r'^\s*\d+%\|')
_STEP = re.compile(r'\*\*\* Step number (\d+) \*\*\*')
_NEW_BRANCH = 'Post Branches are'          # printed each time SeqSeg starts on another branch


def _log_line(line: str) -> None:
    """SeqSeg's words go to the log; nnU-Net's per-prediction bar (one per step, hundreds) does not."""
    s = strip_ansi(line).rstrip()
    if not s.strip() or _TQDM.match(s):
        return
    console.info(s)


class _Tracing:
    """Follows SeqSeg's step counter in its out.txt and reports it as progress."""

    def __init__(self, work: Path, max_steps: int):
        self.work, self.max_steps = Path(work), int(max_steps)
        self.path = None
        self.offset = 0
        self.step = -1
        self.branch = 1
        self.first = None            # (step, time) when the counter was first seen, for the rate

    def _find(self):
        if self.path is None or not self.path.exists():
            found = list(self.work.glob('seqseg*/out.txt'))
            self.path = max(found, key=lambda p: p.stat().st_mtime) if found else None
        return self.path

    def read(self, text: str) -> bool:
        """Take in new text of the log; True when the step counter moved."""
        steps = [int(s) for s in _STEP.findall(text)]
        self.branch += text.count(_NEW_BRANCH)
        if not steps or max(steps) <= self.step:
            return False
        self.step = max(steps)
        if self.first is None:
            self.first = (self.step, time.time())
        return True

    def text(self) -> str:
        s = 'step %d of up to %d, branch %d' % (self.step + 1, self.max_steps, self.branch)
        done = self.step - self.first[0]
        if done >= 4:
            per = (time.time() - self.first[1]) / done
            left = per * (self.max_steps - self.step)
            s += ' (%.1f s per step, at most %s more)' % (per, '%.0f min' % (left / 60) if left >= 90 else '%.0f s' % left)
        return s

    def poll(self) -> None:
        p = self._find()
        if p is None:
            return
        try:
            with open(p, 'rb') as f:
                f.seek(self.offset)
                new = f.read()
        except OSError:
            return
        if not new:
            return
        self.offset += len(new)
        if self.read(new.decode('utf-8', 'replace')):
            console.progress(self.step + 1, self.max_steps, self.text())


ITK_SUFFIXES = ('.nii', '.nii.gz', '.mha', '.mhd', '.nrrd', '.nhdr', '.dcm', '.hdr', '.img')


def _image_for_seqseg(case, image: Path) -> Path:
    """
    SeqSeg reads what SimpleITK reads. A VTK image (.vti, .vtk) is converted
    once into work/image.mha, keeping spacing, origin and orientation, so seed
    coordinates picked on it still mean the same point.
    """
    if image.name.lower().endswith(ITK_SUFFIXES):
        return image
    if image.suffix.lower() not in ('.vti', '.vtk'):
        return image
    import pyvista as pv
    import SimpleITK as sitk
    grid = pv.read(str(image))
    if not isinstance(grid, pv.ImageData):
        raise ConfigError("segmentation.image %s is a %s, not a regular image volume"
                          % (image.name, type(grid).__name__))
    name = grid.point_data.active_scalars_name or (grid.point_data.keys() or [None])[0]
    if name is None:
        raise ConfigError("segmentation.image %s carries no point data to segment" % image.name)
    arr = np.ascontiguousarray(grid.point_data[name]).reshape(grid.dimensions[::-1])   # keep the scan's dtype
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing(tuple(float(s) for s in grid.spacing))
    img.SetOrigin(tuple(float(o) for o in grid.origin))
    d = getattr(grid, 'direction_matrix', None)
    if d is not None:
        img.SetDirection(tuple(float(v) for v in np.asarray(d).ravel()))
    case.work.mkdir(parents=True, exist_ok=True)
    target = case.work / (image.stem + '.mha')     # keep the case name SeqSeg derives from the file
    sitk.WriteImage(img, str(target))
    console.info('converted %s to %s for SeqSeg (%s)' % (image.name, target.name, 'x'.join(map(str, grid.dimensions))))
    return target


def _inlet_plane(sg) -> dict:
    """
    The inlet is where the user put the first seed: a plane through that
    point, cutting off whatever lies behind it. The seed already carries
    the two things the cut needs, the direction along the vessel and the
    radius there, so nothing has to be guessed from the surface.
    """
    s = sg.seeds[0]
    p, d = np.asarray(s.point, float), np.asarray(s.direction, float)
    n = p - d                                   # away from the vessel: the side to discard
    ln = float(np.linalg.norm(n))
    r = float(s.radius)
    return dict(name='inlet', origin=[float(v) for v in p], radius=r, inlet=True,
                normal=[float(v) for v in (n / ln if ln > 1e-12 else np.array([0.0, 0.0, 1.0]))],
                box_width=1.6 * r, box_length=4.0 * r)


def _with_seed_inlet(planes, sg, min_separation: float = 1.5) -> list:
    """
    Put the seed's own plane in front as the inlet. Ends in that same piece
    of vessel are kept as candidates but switched off, so the outlet editor
    can still show them.
    """
    inlet = _inlet_plane(sg)
    o = np.asarray(inlet['origin'], float)
    out = [inlet]
    for q in planes:
        d = dict(q, inlet=False)
        if q.get('inlet'):
            d['use'], d['skipped'] = False, 'the seed is the inlet'
        elif np.linalg.norm(np.asarray(q['origin'], float) - o) < min_separation * max(q['radius'], inlet['radius']):
            d['use'], d['skipped'] = False, 'same vessel end as the inlet'
        out.append(d)
    n = 0
    for q in out:
        if q['inlet']:
            q['name'] = 'inlet'
        else:
            n += 1
            q['name'] = 'cap_%d' % n
    return out


def run(case):
    sg = case.config.segmentation
    image = case.resolve(sg.image)
    if not image.exists():
        raise ConfigError("segmentation.image not found: %s" % image)
    if not sg.seeds:
        raise ConfigError("segmentation.seeds is empty: place a seed on the Segment step of `miros gui`, "
                          "or add {point, direction, radius} entries to %s" % case.yaml)
    folder = _model_folder(case)
    config_name = _config_name(case)
    model_units = MODELS[sg.model]['unit'] if sg.model in MODELS else sg.units
    dataset = MODELS[sg.model]['dataset'] if sg.model in MODELS else folder.parent.name
    image = _image_for_seqseg(case, image)
    out = case.work / 'seqseg'
    for stale in [out] + sorted(case.work.glob('seqseg3d_*')) + sorted(case.work.glob('seqseg*_fullres_*')):
        if stale.exists():                     # SeqSeg refuses to overwrite its own output tree
            shutil.rmtree(stale, ignore_errors=True)
    out.mkdir(parents=True)

    # seeds.json: [[start point, direction point, radius], ...]; the case name must match the image stem
    stem = image.name
    for suf in ('.nii.gz', '.nii', '.mha', '.mhd', '.nrrd', '.vti'):
        if stem.lower().endswith(suf):
            stem = stem[:-len(suf)]
            break
    seeds = [[list(map(float, s.point)), list(map(float, s.direction)), float(s.radius)] for s in sg.seeds]
    seeds_json = out / 'seeds.json'
    seeds_json.write_text(json.dumps([{'name': stem, 'seeds': seeds, 'cardiac_mesh': False}], indent=2))

    cmd = [sys.executable, '-u', '-m', 'seqseg.seqseg', 'run', 'single',      # -u: its lines arrive as printed
           '--image', str(image), '--outdir', str(out), '--model-folder', str(folder),
           '--train-dataset', dataset, '--config-name', config_name,
           '--unit', sg.units, '--scale', '%g' % _scale(sg.units, model_units),
           '--max-n-steps', str(sg.max_steps), '--max-n-branches', str(sg.max_branches),
           '--max-n-steps-per-branch', str(sg.max_steps_per_branch),
           '--assembly-threshold', '%g' % sg.assembly_threshold,
           '--extract-global-centerline', '1' if sg.extract_centerline else '0',
           '--cap-surface-cent', '0',       # SeqSeg's own capping is fragile; MIROS clips the ends itself
           '--seeds-json', str(seeds_json)]
    console.info('SeqSeg: %s (%s), config %s, %d seed(s), image units %s, scale %g' % (
        sg.model, dataset, config_name, len(seeds), sg.units, _scale(sg.units, model_units)))
    console.info('tracing: %d steps total, %d branches, %d steps per branch, assembly at %g%s' % (
        sg.max_steps, sg.max_branches, sg.max_steps_per_branch, sg.assembly_threshold,
        ', centerline of the whole tree' if sg.extract_centerline else ''))
    log = out / 'seqseg.log'
    tracing = _Tracing(case.work, sg.max_steps)
    console.progress(0, sg.max_steps, 'starting SeqSeg (loading the model) ...')
    t0 = time.time()
    code = run_logged(cmd, log, cwd=out, on_line=_log_line, cancel=case.cancel, poll=tracing.poll, poll_interval=1.0,
                      name='SeqSeg')
    console.progress(None)
    if tracing.step >= 0:
        console.info('traced %d steps on %d branch(es) in %.0f s' % (tracing.step + 1, tracing.branch, time.time() - t0))
    if code != 0:
        tail = log.read_text(encoding='utf-8', errors='replace').splitlines()[-25:]
        why = ''
        if code == -9:
            why = (" Exit -9 means the process was killed, which on Linux is usually the kernel running out "
                   "of memory (see `dmesg`); a shorter trace with extract_centerline off needs far less.")
        raise RuntimeError("SeqSeg failed (exit %d).%s Log tail:\n%s" % (code, why, '\n'.join(tail)))

    surfaces = [p for p in out.rglob('*_surface_mesh_*_steps.vtp') if 'nonsmooth' not in p.name]
    if not surfaces:
        raise RuntimeError("SeqSeg produced no surface (see %s)" % log)
    surface = max(surfaces, key=_steps_in_name)
    cls = list(out.rglob('*_centerlines.vtp')) + list(out.rglob('*_centerline_*.vtp'))
    centerline = max(cls, key=_steps_in_name) if cls else None
    shutil.copy(surface, case.work / 'seqseg_surface.vtp')
    console.info('surface: %s (%d steps)' % (surface.name, _steps_in_name(surface)))

    planes = []
    if centerline is not None:
        shutil.copy(centerline, case.work / 'seqseg_centerline.vtp')
        planes = propose_outlet_planes(read_polydata(centerline), back_off=sg.outlet_back_off,
                                       seed_point=sg.seeds[0].point)
        planes = _with_seed_inlet(planes, sg)
        console.info('%d vessel ends from the tracked centerline (%s)' % (len(planes), centerline.name))
    if not planes:
        (case.work / 'seqseg_centerline.vtp').unlink(missing_ok=True)
        console.info('finding the vessel ends on the surface itself (medial axis from the seed) ...')
        planes = propose_from_closed_surface(read_polydata(surface), sg.seeds[0].point, back_off=sg.outlet_back_off)
        planes = _with_seed_inlet(planes, sg)
        console.info('%d vessel ends found on the surface' % len(planes))
    if not planes:
        console.warn('no vessel ends found; give the outlet planes under model.outlets')
    (case.work / 'outlets_proposed.json').write_text(json.dumps(planes, indent=2))
    on = [p['name'] for p in planes if p.get('use', True)]
    console.info('proposed as cuts: %s' % (', '.join(on) if on else 'none'))
    console.info('review them on the Outlets step (`miros gui`) or in %s before the surface is clipped'
                 % (case.work / 'outlets_proposed.json'))
    return outputs(case)
