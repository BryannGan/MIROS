import json

import numpy as np
import pytest
import pyvista as pv

from miros.config import ConfigError, load_config, write_template
from miros.geometry.outlets import propose_outlet_planes
from miros.models import MODELS, TRAINER, download_url, find_model_folder


def test_model_registry_and_folder_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv('MIROS_MODELS_DIR', str(tmp_path))
    assert find_model_folder('aorta_ct') is None
    trainer = tmp_path / 'aorta' / MODELS['aorta_ct']['dataset'] / TRAINER
    trainer.mkdir(parents=True)
    (trainer / 'plans.json').write_text('{}')
    assert find_model_folder('aorta_ct') == trainer
    assert find_model_folder(str(trainer)) == trainer                  # a path is accepted too
    assert find_model_folder(str(tmp_path / 'aorta')) == trainer       # or a folder containing it
    assert download_url('coronary_ct').startswith('https://zenodo.org/api/records/19547894/files/')


def _tracked_centerline():
    """Two paths sharing a trunk, with radii, as SeqSeg writes them."""
    trunk = np.array([[0, 0, z] for z in np.linspace(0, 10, 21)], float)
    a = np.array([[x, 0, 10 + 0.3 * x] for x in np.linspace(0.5, 8, 16)], float)
    b = np.array([[-x, 0, 10 + 0.3 * x] for x in np.linspace(0.5, 8, 16)], float)
    pts = np.vstack([trunk, a, b])
    n_t, n_a = len(trunk), len(a)
    cid = np.zeros((len(pts), 2), dtype=np.int32)
    cid[:n_t + n_a, 0] = 1                       # path 0: trunk + a
    cid[:n_t, 1] = 1; cid[n_t + n_a:, 1] = 1     # path 1: trunk + b
    cl = pv.PolyData(pts)
    lines = []
    for idx in (list(range(n_t + n_a)), list(range(n_t)) + list(range(n_t + n_a, len(pts)))):
        lines += [len(idx)] + idx
    cl.lines = np.array(lines)
    cl.point_data['CenterlineId'] = cid
    cl.point_data['MaximumInscribedSphereRadius'] = np.where(np.arange(len(pts)) < n_t, 1.0, 0.5)
    return cl


def test_propose_outlet_planes_from_tracked_centerline():
    planes = propose_outlet_planes(_tracked_centerline(), back_off=2.0)
    assert len(planes) == 3
    inlet = [p for p in planes if p['inlet']]
    assert len(inlet) == 1 and inlet[0]['name'] == 'inlet'
    # the inlet plane sits 2 radii up the trunk and its normal points back toward the trunk start
    assert abs(inlet[0]['origin'][2] - 2.0) < 0.6 and inlet[0]['normal'][2] < -0.9
    outs = [p for p in planes if not p['inlet']]
    assert all(p['radius'] == 0.5 for p in outs)
    assert all(abs(abs(p['normal'][0]) - 1 / np.sqrt(1 + 0.09)) < 0.1 for p in outs)   # along the branches, toward the tips


def test_segmentation_config_roundtrip_and_validation(tmp_path):
    p = tmp_path / 'case.yaml'
    write_template(p, surface=None, image='input/scan.nii.gz', image_units='mm', seg_model='aorta_ct',
                   seeds=[{'point': [1, 2, 3], 'direction': [1, 2, 4], 'radius': 1.1}])
    cfg = load_config(p)
    assert cfg.segmentation.image == 'input/scan.nii.gz' and cfg.model.surface is None
    assert cfg.segmentation.seeds[0].radius == 1.1 and cfg.segmentation.seeds[0].direction == [1.0, 2.0, 4.0]
    # a case created from an image has no seeds yet: that loads, and the stage says what is missing
    seedless = tmp_path / 'bad.yaml'
    write_template(seedless, surface=None, image='input/scan.nii.gz')
    assert load_config(seedless).segmentation.seeds == []
    write_template(tmp_path / 'none.yaml', surface=None)                                # neither
    with pytest.raises(ConfigError, match='model.surface or segmentation.image'):
        load_config(tmp_path / 'none.yaml')


def test_segment_stage_refuses_without_seeds(tmp_path):
    """A case created from an image loads without seeds; the stage is what asks for them."""
    from miros.case import Case
    from miros.stages import segment
    (tmp_path / 'input').mkdir()
    img = tmp_path / 'input' / 'scan.nii.gz'
    img.write_bytes(b'not a real volume')
    write_template(tmp_path / 'case.yaml', surface=None, image='input/scan.nii.gz')
    case = Case(tmp_path)
    assert segment.enabled(case)
    with pytest.raises(ConfigError, match='seeds'):
        segment.run(case)


def test_seqseg_config_is_chosen_per_model_and_checked(tmp_path):
    """SeqSeg 2.1 ships a `global` config with no ADD_RADIUS, which dies mid-trace: catch it up front."""
    from miros.case import Case
    from miros.stages.segment import _config_name, _seqseg_configs
    (tmp_path / 'input').mkdir()
    (tmp_path / 'input' / 'scan.nii.gz').write_bytes(b'x')
    p = tmp_path / 'case.yaml'
    write_template(p, surface=None, image='input/scan.nii.gz', seg_model='aorta_ct',
                   seeds=[{'point': [0, 0, 0], 'direction': [0, 0, 1], 'radius': 1.0}])
    available = _seqseg_configs()
    if not available:
        pytest.skip('seqseg is not installed')
    assert _config_name(Case(tmp_path)) == MODELS['aorta_ct']['config']
    from miros.config_edit import set_values
    set_values(p, {'segmentation.config_name': 'no_such_config'})
    with pytest.raises(ConfigError, match='available'):
        _config_name(Case(tmp_path))
    if 'global' in available and 'ADD_RADIUS' not in available['global'].read_text():
        set_values(p, {'segmentation.config_name': 'global'})
        with pytest.raises(ConfigError, match='ADD_RADIUS'):
            _config_name(Case(tmp_path))


def test_vtk_image_is_converted_for_seqseg(tmp_path):
    """SeqSeg reads what SimpleITK reads, so a .vti volume is converted once, keeping its geometry."""
    sitk = pytest.importorskip('SimpleITK')
    from miros.case import Case
    from miros.stages.segment import _image_for_seqseg
    (tmp_path / 'input').mkdir()
    grid = pv.ImageData(dimensions=(8, 9, 10), spacing=(0.4, 0.5, 0.6), origin=(1.0, -2.0, 3.0))
    grid.point_data['scalars'] = np.arange(grid.n_points, dtype=np.float32)
    src = tmp_path / 'input' / 'scan.vti'
    grid.save(str(src))
    write_template(tmp_path / 'case.yaml', surface=None, image='input/scan.vti',
                   seeds=[{'point': [1, 1, 4], 'direction': [1, 1, 5], 'radius': 0.5}])
    case = Case(tmp_path)
    out = _image_for_seqseg(case, src)
    assert out.suffix == '.mha' and out.exists()
    img = sitk.ReadImage(str(out))
    assert img.GetSize() == (8, 9, 10)
    assert np.allclose(img.GetSpacing(), (0.4, 0.5, 0.6)) and np.allclose(img.GetOrigin(), (1.0, -2.0, 3.0))
    assert np.allclose(sitk.GetArrayFromImage(img).ravel(order='C'), np.arange(720))
    # an ITK-readable file is passed through untouched
    assert _image_for_seqseg(case, tmp_path / 'input' / 'scan.nii.gz') == tmp_path / 'input' / 'scan.nii.gz'
