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
import subprocess
import sys
from pathlib import Path

import numpy as np

from ..config import ConfigError
from ..geometry.caps import read_polydata
from ..geometry.outlets import propose_from_closed_surface, propose_outlet_planes
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
    The SeqSeg tracing config: the one named in case.yaml, else the one that
    suits the model. Some configs shipped upstream are incomplete (SeqSeg 2.1's
    `global` has no ADD_RADIUS and dies mid-trace), so the choice is checked here
    rather than an hour into a run.
    """
    sg = case.config.segmentation
    name = sg.config_name or MODELS.get(sg.model, {}).get('config') or 'global_default'
    available = _seqseg_configs()
    if not available:
        return name                                  # SeqSeg not importable here; let the subprocess complain
    if name not in available:
        raise ConfigError("segmentation.config_name %r is not a SeqSeg config; available: %s"
                          % (name, ', '.join(sorted(available))))
    import yaml
    keys = {}
    for n, path in available.items():
        try:
            keys[n] = set(yaml.safe_load(path.read_text(errors='replace')) or {})
        except Exception:                                # noqa: BLE001 - unreadable config
            keys[n] = set()
    complete = max(keys.values(), key=len, default=set())     # the settings a full config carries
    missing = sorted(complete - keys.get(name, set()))
    if missing:
        good = sorted(n for n, k in keys.items() if not (complete - k))
        raise ConfigError("the SeqSeg config %r is missing %s, so tracing would stop part way through. "
                          "Set segmentation.config_name to one of: %s" % (name, ', '.join(missing), ', '.join(good)))
    return name


def _steps_in_name(p: Path) -> int:
    m = re.search(r'_(\d+)_steps', p.name)
    return int(m.group(1)) if m else -1


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

    cmd = [sys.executable, '-m', 'seqseg.seqseg', 'run', 'single',
           '--image', str(image), '--outdir', str(out), '--model-folder', str(folder),
           '--train-dataset', dataset, '--config-name', config_name,
           '--unit', sg.units, '--scale', '%g' % _scale(sg.units, model_units),
           '--max-n-steps', str(sg.max_steps), '--max-n-branches', str(sg.max_branches),
           '--max-n-steps-per-branch', str(sg.max_steps_per_branch),
           '--seeds-json', str(seeds_json)]
    console.info('SeqSeg: %s (%s), config %s, %d seed(s), image units %s, scale %g' % (
        sg.model, dataset, config_name, len(seeds), sg.units, _scale(sg.units, model_units)))
    log = out / 'seqseg.log'
    with open(log, 'w', encoding='utf-8', newline='\n') as f:
        proc = subprocess.run(cmd, cwd=str(out), stdout=f, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        tail = log.read_text(errors='replace').splitlines()[-25:]
        raise RuntimeError("SeqSeg failed (exit %d). Log tail:\n%s" % (proc.returncode, '\n'.join(tail)))

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
        planes = propose_outlet_planes(read_polydata(centerline), back_off=sg.outlet_back_off)
        console.info('proposed %d cut planes from the tracked centerline (%s)' % (len(planes), centerline.name))
    if not planes:
        (case.work / 'seqseg_centerline.vtp').unlink(missing_ok=True)
        console.info('finding the vessel ends on the surface itself (medial axis from the seed) ...')
        planes = propose_from_closed_surface(read_polydata(surface), sg.seeds[0].point, back_off=sg.outlet_back_off)
        console.info('proposed %d cut planes (%s)' % (len(planes), ', '.join(p['name'] for p in planes)))
    if not planes:
        console.warn('no vessel ends found; give the outlet planes under model.outlets')
    (case.work / 'outlets_proposed.json').write_text(json.dumps(planes, indent=2))
    return outputs(case)
