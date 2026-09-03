"""
Pre-trained SeqSeg (nnU-Net) models: where they come from, where they live,
and how to fetch them.

    miros models list
    miros models download aorta_ct

Weights are published on Zenodo by the SeqSeg authors (CC-BY-4.0) and are
extracted under ~/.miros/models (override with MIROS_MODELS_DIR). SeqSeg
needs the trainer folder, e.g.
    <root>/Dataset006_SEQAORTANDFEMOCT/nnUNetTrainer__nnUNetPlans__3d_fullres
"""
import os
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, Optional

MODELS: Dict[str, dict] = {
    'aorta_ct': dict(
        description='Aorta and femoral arteries, CT (Vascular Model Repository)',
        record=15020477, file='nnUNet_results.zip', size=236318244,
        dataset='Dataset006_SEQAORTANDFEMOCT', unit='cm', modality='CT',
        doi='10.5281/zenodo.15020477'),
    'aorta_mr': dict(
        description='Aorta and femoral arteries, MR (Vascular Model Repository)',
        record=15020477, file='nnUNet_results.zip', size=236318244,
        dataset='Dataset005_SEQAORTANDFEMOMR', unit='cm', modality='MR',
        doi='10.5281/zenodo.15020477'),
    'coronary_ct': dict(
        description='Coronary arteries, CT angiography',
        record=19547894, file='nnUNet_results_coronary.zip', size=2793144,
        dataset='Dataset010_SEQCOROASOCACT', unit='mm', modality='CT',
        doi='10.5281/zenodo.19547894'),
}
TRAINER = 'nnUNetTrainer__nnUNetPlans__3d_fullres'


def models_dir() -> Path:
    d = os.environ.get('MIROS_MODELS_DIR')
    return Path(d).expanduser() if d else Path.home() / '.miros' / 'models'


def download_url(name: str) -> str:
    m = MODELS[name]
    return 'https://zenodo.org/api/records/%d/files/%s/content' % (m['record'], m['file'])


def find_model_folder(name_or_path: str) -> Optional[Path]:
    """
    The nnU-Net trainer folder for a registry name (searched under
    models_dir) or a path given directly (the trainer folder itself, or a
    folder containing it).
    """
    p = Path(name_or_path).expanduser()
    if p.exists():
        if (p / 'plans.json').exists() or (p / 'dataset.json').exists():
            return p
        hits = sorted(p.rglob(TRAINER))
        return hits[0] if hits else None
    if name_or_path not in MODELS:
        return None
    root = models_dir()
    if not root.exists():
        return None
    hits = sorted(root.rglob(os.path.join(MODELS[name_or_path]['dataset'], TRAINER)))
    return hits[0] if hits else None


def download(name: str, progress=None) -> Path:
    """Download and extract a registry model; returns its trainer folder."""
    if name not in MODELS:
        raise KeyError("unknown model %r; known: %s" % (name, sorted(MODELS)))
    found = find_model_folder(name)
    if found is not None:
        return found
    m = MODELS[name]
    root = models_dir()
    root.mkdir(parents=True, exist_ok=True)
    zip_path = root / m['file']
    if not zip_path.exists() or zip_path.stat().st_size != m['size']:
        url = download_url(name)

        def hook(count, block, total):
            if progress:
                progress(min(count * block, total), total)
        urllib.request.urlretrieve(url, str(zip_path), reporthook=hook)
    target = root / Path(m['file']).stem
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(target)
    found = find_model_folder(name)
    if found is None:
        raise RuntimeError("downloaded %s but could not find %s/%s under %s" % (m['file'], m['dataset'], TRAINER, target))
    return found


def status() -> Dict[str, Optional[Path]]:
    return {k: find_model_folder(k) for k in MODELS}


def cli_progress(done, total):
    pct = 100.0 * done / total if total else 0.0
    sys.stdout.write('\r  downloading %5.1f%% (%.0f / %.0f MB)' % (pct, done / 1e6, total / 1e6))
    sys.stdout.flush()
    if total and done >= total:
        sys.stdout.write('\n')
