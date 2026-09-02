"""`miros init` + `miros run` on the test case through the 0D stages, with re-run and --from semantics."""
import json

import pytest
import yaml

from miros.case import Case
from miros.cli import main

pytestmark = pytest.mark.slow


@pytest.fixture(scope='module')
def case_dir(surface_path, tmp_path_factory):
    inflow = surface_path.parent / 'inflow_1d.flow'
    if not inflow.exists():
        pytest.skip("inflow file missing")
    pytest.importorskip('pysvzerod')
    d = tmp_path_factory.mktemp('case')
    assert main(['init', str(d), '--surface', str(surface_path), '--inflow', str(inflow), '--name', 't']) == 0
    y = d / 'case.yaml'
    cfg = yaml.safe_load(y.read_text())
    outlets = list(cfg['boundary_conditions']['flow_split'])
    assert len(outlets) == 5
    cfg['boundary_conditions']['flow_split'] = dict(zip(outlets, [50, 20, 10, 10, 10]))
    cfg['boundary_conditions']['pressure_mmHg'] = {'at': outlets[0], 'systolic': 110, 'diastolic': 70, 'mean': None}
    cfg['boundary_conditions']['tolerance_pct'] = 8      # this test exercises the case flow, not tuner precision
    cfg['simulation']['run_1d'] = False
    y.write_text(yaml.safe_dump(cfg))
    return d


def test_run_through_0d(case_dir):
    assert main(['run', str(case_dir)]) == 0
    c = Case(case_dir)
    for p in (c.surface_work, c.caps_json, c.centerlines, c.zerod_json, c.rcrt, c.tuning_report,
              c.results_0d / '0D_results.csv', c.results_0d / '0D_statistics.csv'):
        assert p.exists(), p
    rep = json.loads(c.tuning_report.read_text())
    assert rep['converged'], rep['errors_pct']
    summary = json.loads((c.results_0d / '0D_summary.json').read_text())
    splits = {o['outlet']: o['flow_split_pct'] for o in summary['outlets']}
    target = dict(zip(c.outlet_names(), [50, 20, 10, 10, 10]))
    for k, v in target.items():
        assert abs(splits[k] - v) < 0.05 * v + 0.5, (k, splits[k], v)


def test_second_run_does_nothing(case_dir):
    c = Case(case_dir)
    assert c.run() == []


def test_from_tune_reruns_downstream_only(case_dir):
    c = Case(case_dir)
    ran = c.run(from_stage='tune')
    assert ran[0] == 'tune' and 'preprocess' not in ran and 'rom_model' not in ran
    assert 'sim_0d' in ran and 'extract_0d' in ran


def test_changing_a_target_makes_tune_stale(case_dir):
    y = case_dir / 'case.yaml'
    cfg = yaml.safe_load(y.read_text())
    cfg['boundary_conditions']['pressure_mmHg']['systolic'] = 115
    y.write_text(yaml.safe_dump(cfg))
    states = dict((s, st) for s, st, _ in Case(case_dir).status())
    assert states['preprocess'] == 'fresh' and states['rom_model'] == 'fresh'
    assert states['tune'] == 'stale'
    assert main(['status', str(case_dir)]) == 0
