import numpy as np

from miros.io import inflow as IO_inflow
from miros.io.rcrt import DEFAULT_RCR, read_rcrt, write_default_rcrt, write_rcrt


def test_rcrt_roundtrip(tmp_path):
    rcr = {'cap_a': {'Rp': 12.5, 'C': 1.5e-4, 'Rd': 987.0}, 'cap_b': {'Rp': 3.0, 'C': 2e-3, 'Rd': 40.0}}
    p = tmp_path / 'rcrt.dat'
    write_rcrt(rcr, ['cap_b', 'cap_a'], p)
    back = read_rcrt(p)
    assert list(back) == ['cap_b', 'cap_a']          # order preserved
    for k in rcr:
        for f in ('Rp', 'C', 'Rd'):
            assert back[k][f] == rcr[k][f]
    text = p.read_text()
    assert text.startswith('2\n') and '\r' not in text


def test_rcrt_default_template(tmp_path):
    p = tmp_path / 'rcrt.dat'
    write_default_rcrt(['x', 'y', 'z'], p)
    back = read_rcrt(p)
    assert list(back) == ['x', 'y', 'z']
    assert back['y'] == DEFAULT_RCR


def test_inflow_roundtrip_and_stats(tmp_path):
    t = np.linspace(0, 0.8, 401)
    q = 100 * np.sin(np.pi * t / 0.8) ** 2
    p = tmp_path / 'in.flow'
    IO_inflow.write_inflow(t, q, p)
    t2, q2 = IO_inflow.read_inflow(p)
    assert np.allclose(t, t2, atol=1e-6) and np.allclose(q, q2, atol=1e-5)
    assert abs(IO_inflow.cycle_duration(p) - 0.8) < 1e-6
    assert abs(IO_inflow.time_step(p) - 0.002) < 1e-6
    assert IO_inflow.num_time_steps(p, 3) == 3 * 401
    assert abs(IO_inflow.mean_flow(p) - 50.0) < 0.5
