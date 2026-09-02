from miros.manifest import Manifest, file_hash, value_hash


def test_stage_freshness_tracks_inputs_and_outputs(tmp_path):
    src = tmp_path / 'in.txt'
    src.write_text('a')
    out = tmp_path / 'out.txt'
    out.write_text('result')
    m = Manifest(tmp_path / '.miros' / 'manifest.json')
    inputs = {'src': file_hash(src), 'cfg': value_hash({'k': 1})}
    assert m.status('s', inputs)[0] == 'never'
    m.record('s', inputs, [str(out)])
    assert m.status('s', inputs)[0] == 'fresh'
    # config change
    assert m.status('s', {'src': file_hash(src), 'cfg': value_hash({'k': 2})}) == ('stale', 'input changed: cfg')
    # input file change
    src.write_text('b')
    assert m.status('s', {'src': file_hash(src), 'cfg': value_hash({'k': 1})})[0] == 'stale'
    # output missing
    out.unlink()
    assert m.status('s', inputs)[0] == 'stale'
    # persists across instances
    m2 = Manifest(tmp_path / '.miros' / 'manifest.json')
    assert 's' in m2.data


def test_value_hash_is_order_independent():
    assert value_hash({'a': 1, 'b': [1, 2]}) == value_hash({'b': [1, 2], 'a': 1})
    assert value_hash({'a': 1}) != value_hash({'a': 2})
