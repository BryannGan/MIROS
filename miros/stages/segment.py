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


def _steps_in_name(p: Path) -> int:
    m = re.search(r'_(\d+)_steps', p.name)
    return int(m.group(1)) if m else -1


def run(case):
    sg = case.config.segmentation
    image = case.resolve(sg.image)
    if not image.exists():
        raise ConfigError("segmentation.image not found: %s" % image)
    if not sg.seeds:
        raise ConfigError("segmentation.seeds is empty: place a seed on the Segment step of `miros gui`, "
                          "or add {point, direction, radius} entries to %s" % case.yaml)
    folder = _model_folder(case)
    model_units = MODELS[sg.model]['unit'] if sg.model in MODELS else sg.units
    dataset = MODELS[sg.model]['dataset'] if sg.model in MODELS else folder.parent.name
    out = case.work / 'seqseg'
    if out.exists():
        shutil.rmtree(out)
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
           '--train-dataset', dataset, '--config-name', sg.config_name,
           '--unit', sg.units, '--scale', '%g' % _scale(sg.units, model_units),
           '--max-n-steps', str(sg.max_steps), '--max-n-branches', str(sg.max_branches),
           '--max-n-steps-per-branch', str(sg.max_steps_per_branch),
           '--seeds-json', str(seeds_json)]
    console.info('SeqSeg: %s (%s), %d seed(s), image units %s, scale %g' % (
        sg.model, dataset, len(seeds), sg.units, _scale(sg.units, model_units)))
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
