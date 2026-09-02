from miros.timestep import recommended_samples_per_cycle, wave_speed


def test_recommendation_is_sane_for_the_aorta():
    # test case: 0.6 s cycle, 610 mL/s peak, inlet 5.15 cm^2, smallest cap 0.29 cm^2, MIROS material defaults
    n, d = recommended_samples_per_cycle(0.6, 610.0, 5.15, 0.29)
    assert 1000 <= n <= 6000 and n % 100 == 0
    assert 100 < d['v_peak'] < 130 and 1500 < d['wave_speed'] < 3000 and 0.5 < d['dx'] < 0.7
    assert abs(0.6 / (d['dt_ms'] / 1000.0) - n) < 100 + 1e-6 or n == 600


def test_recommendation_grows_with_speed_and_shrinks_with_size():
    n1, _ = recommended_samples_per_cycle(0.8, 300.0, 5.0, 0.5)
    n2, _ = recommended_samples_per_cycle(0.8, 300.0, 5.0, 0.1)      # smaller vessel -> more samples
    n3, _ = recommended_samples_per_cycle(0.8, 300.0, 5.0, 0.5, k3=1e6)   # softer wall -> slower wave -> fewer
    assert n2 > n1 >= n3
    assert wave_speed(1.0, 0.0, 0.0, 1e7, 1.06) > wave_speed(1.0, 0.0, 0.0, 1e6, 1.06)
