"""`miros install`: which release asset fits this machine, where it lands, and the fallbacks."""
import json
import os
import platform
import stat

import pytest

from miros import install as I


def test_platform_key_and_asset_names():
    assert I.platform_key('Linux', 'x86_64') == 'linux-x86_64'
    assert I.platform_key('Darwin', 'arm64') == 'macos-arm64'
    assert I.platform_key('Darwin', 'x86_64') == 'macos-x86_64'
    assert I.platform_key('Windows', 'AMD64') == 'windows-x86_64'
    assert I.onedsolver_asset('windows-x86_64') == 'OneDSolver-windows-x86_64.exe'
    assert I.onedsolver_asset('macos-arm64') == 'OneDSolver-macos-arm64'
    with pytest.raises(I.InstallError, match='no prebuilt'):
        I.platform_key('Linux', 'riscv64')


def test_wheel_matching_by_interpreter_and_platform():
    assert I.wheel_matches('pysvzerod-2.0-cp311-cp311-linux_x86_64.whl', 'linux-x86_64', (3, 11))
    assert not I.wheel_matches('pysvzerod-2.0-cp310-cp310-linux_x86_64.whl', 'linux-x86_64', (3, 11))
    assert I.wheel_matches('pysvzerod-2.0-cp312-cp312-macosx_11_0_arm64.whl', 'macos-arm64', (3, 12))
    assert not I.wheel_matches('pysvzerod-2.0-cp312-cp312-macosx_11_0_arm64.whl', 'macos-x86_64', (3, 12))
    assert I.wheel_matches('pysvzerod-2.0-cp310-cp310-win_amd64.whl', 'windows-x86_64', (3, 10))
    assert not I.wheel_matches('OneDSolver-linux-x86_64', 'linux-x86_64', (3, 11))


def _release(*names):
    body = {'assets': [{'name': n, 'browser_download_url': 'https://example.invalid/' + n, 'size': 1000} for n in names]}
    return lambda url: json.dumps(body).encode()


def _fake_download(url, target, progress=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('#!/bin/sh\nexit 0\n')
    return target


def test_onedsolver_lands_in_miros_home_and_is_found_first(tmp_path, monkeypatch):
    monkeypatch.setenv('MIROS_HOME', str(tmp_path))
    monkeypatch.delenv('MIROS_ONEDSOLVER', raising=False)
    key = I.platform_key()
    p = I.install_onedsolver(log=lambda s: None, fetch=_release(I.onedsolver_asset(key), 'other-file'),
                             fetch_file=_fake_download, verify=False)
    assert p.parent == tmp_path / 'bin' and p.exists()
    if os.name != 'nt':
        assert p.stat().st_mode & stat.S_IXUSR
    from miros.solvers import find_onedsolver
    assert find_onedsolver() == str(p)
    with pytest.raises(I.InstallError, match='no prebuilt OneDSolver'):
        I.install_onedsolver(log=lambda s: None, fetch=_release('nothing-useful'), fetch_file=_fake_download, verify=False)


def _wheel_name_for_here():
    key = I.platform_key()
    plat = {'linux': 'linux_x86_64', 'macos': 'macosx_11_0_' + key.split('-')[1], 'windows': 'win_amd64'}[key.split('-')[0]]
    import sys
    return 'pysvzerod-2.0-cp%d%d-cp%d%d-%s.whl' % (sys.version_info[0], sys.version_info[1],
                                                   sys.version_info[0], sys.version_info[1], plat)


def test_pysvzerod_takes_the_wheel_then_falls_back_to_source(tmp_path, monkeypatch):
    monkeypatch.setenv('MIROS_HOME', str(tmp_path))
    state = {'installed': False}
    monkeypatch.setattr(I, 'importable', lambda m: state['installed'])
    name = _wheel_name_for_here()

    calls = []

    def run_ok(args):
        calls.append(list(args)); state['installed'] = True; return 0
    how = I.install_pysvzerod(log=lambda s: None, run=run_ok, fetch=_release(name, 'OneDSolver-linux-x86_64'),
                              fetch_file=_fake_download)
    assert how == 'wheel' and calls == [[str(tmp_path / 'wheels' / name)]]

    calls.clear(); state['installed'] = False

    def run_wheel_fails(args):
        calls.append(list(args)); ok = args == [I.ZEROD_GIT]; state['installed'] = ok; return 0 if ok else 1
    how = I.install_pysvzerod(log=lambda s: None, run=run_wheel_fails, fetch=_release(name), fetch_file=_fake_download)
    assert how == 'source' and calls[-1] == [I.ZEROD_GIT]

    calls.clear(); state['installed'] = False
    how = I.install_pysvzerod(log=lambda s: None, run=run_wheel_fails, fetch=_release(), fetch_file=_fake_download)
    assert how == 'source' and calls == [[I.ZEROD_GIT]]                 # no wheel for this machine: straight to source

    state['installed'] = False
    with pytest.raises(I.InstallError, match='did not build'):
        I.install_pysvzerod(log=lambda s: None, run=lambda a: 1, fetch=_release(), fetch_file=_fake_download)

    state['installed'] = True
    assert I.install_pysvzerod(log=lambda s: None, run=lambda a: 1, fetch=_release()) == 'present'


def test_seqseg_installs_torch_for_the_gpu_where_cuda_exists():
    calls = []
    I.install_seqseg(gpu=True, models=(), log=lambda s: None, run=lambda a: calls.append(list(a)) or 0)
    if platform.system() in ('Linux', 'Windows'):
        assert calls[0][:2] == ['torch', '--index-url'] and calls[0][2] == I.TORCH_CUDA_INDEX
    else:
        assert all('torch' not in c[0] for c in calls)
    assert calls[-1][0].startswith('seqseg')
    calls.clear()
    I.install_seqseg(gpu=False, models=(), log=lambda s: None, run=lambda a: calls.append(list(a)) or 0)
    assert len(calls) == 1 and calls[0][0].startswith('seqseg')
