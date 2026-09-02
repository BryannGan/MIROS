import pytest
import yaml

from miros.config import ConfigError, load_config, save_config, write_template, CaseConfig


def test_template_loads_and_validates(tmp_path):
    p = tmp_path / 'case.yaml'
    write_template(p, outlet_names=['a', 'b', 'c'], inlet='in')
    cfg = load_config(p)
    assert cfg.model.inlet == 'in'
    assert abs(sum(cfg.boundary_conditions.flow_split.values()) - 100) < 0.1   # template rounds to 4 digits
    assert cfg.simulation.cycles == 6 and cfg.boundary_conditions.mode == 'tune'


def test_unknown_key_is_an_error(tmp_path):
    p = tmp_path / 'case.yaml'
    write_template(p, outlet_names=['a', 'b'])
    d = yaml.safe_load(p.read_text())
    d['simulation']['cylces'] = 3          # typo
    p.write_text(yaml.safe_dump(d))
    with pytest.raises(ConfigError, match='cylces'):
        load_config(p)


def test_flow_split_must_sum_to_100(tmp_path):
    p = tmp_path / 'case.yaml'
    write_template(p, outlet_names=['a', 'b'])
    d = yaml.safe_load(p.read_text())
    d['boundary_conditions']['flow_split'] = {'a': 60, 'b': 60}
    p.write_text(yaml.safe_dump(d))
    with pytest.raises(ConfigError, match='sums to'):
        load_config(p)


def test_file_mode_needs_a_file(tmp_path):
    p = tmp_path / 'case.yaml'
    write_template(p, outlet_names=['a', 'b'])
    d = yaml.safe_load(p.read_text())
    d['boundary_conditions']['mode'] = 'file'
    p.write_text(yaml.safe_dump(d))
    with pytest.raises(ConfigError, match='boundary_conditions.file'):
        load_config(p)


def test_save_and_reload_roundtrip(tmp_path):
    cfg = CaseConfig()
    cfg.boundary_conditions.flow_split = {'x': 30, 'y': 70}
    cfg.model.units = 'mm'
    p = tmp_path / 'c.yaml'
    save_config(cfg, p)
    back = load_config(p)
    assert back.model.units == 'mm' and back.boundary_conditions.flow_split == {'x': 30, 'y': 70}


def test_yaml_exponent_strings_become_floats(tmp_path):
    p = tmp_path / 'case.yaml'
    write_template(p, outlet_names=['a', 'b'])
    d = yaml.safe_load(p.read_text())
    d['simulation']['material']['olufsen_k3'] = '1.0e7'       # what PyYAML gives for 1.0e7
    d['boundary_conditions']['flow_split'] = {'a': '60', 'b': 40}
    p.write_text(yaml.safe_dump(d))
    cfg = load_config(p)
    assert cfg.simulation.material.olufsen_k3 == 1.0e7 and isinstance(cfg.simulation.material.olufsen_k3, float)
    assert cfg.boundary_conditions.flow_split == {'a': 60.0, 'b': 40.0}


def test_wrong_scalar_types_are_errors(tmp_path):
    p = tmp_path / 'case.yaml'
    write_template(p, outlet_names=['a', 'b'])
    d = yaml.safe_load(p.read_text())
    d['simulation']['cycles'] = 'six'
    p.write_text(yaml.safe_dump(d))
    with pytest.raises(ConfigError, match='simulation.cycles'):
        load_config(p)
