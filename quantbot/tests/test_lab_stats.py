import math

import numpy as np
import pytest

from quantbot.lab import stats as st


def test_basic_metrics():
    r = [1.0, -1.0, 2.0, -0.5]
    assert st.expectancy(r) == pytest.approx(0.375)
    assert st.profit_factor(r) == pytest.approx(3.0 / 1.5)
    assert st.profit_factor([1, 2]) == float("inf") and st.profit_factor([-1]) == 0.0
    assert st.top_k_share([5, 1, 1, 1], 1) == pytest.approx(5 / 8)
    assert st.top_k_share([-1, -2], 3) == 1.0  # profit <= 0 : « tout est concentré »
    assert st.expectancy([]) == 0.0


def test_dsr_penalises_number_of_trials():
    rng = np.random.default_rng(1)
    r = rng.normal(0.2, 1.0, 300)
    one = st.deflated_sharpe(r, 1, 0.0)
    many = st.deflated_sharpe(r, 500, 0.01)
    assert many < one and 0 <= many <= 1
    assert st.deflated_sharpe(r[:5], 1, 0.0) == 0.0  # trop peu de trades


def test_psr_and_min_track_record():
    assert st.psr(0.5, 100, 0.0, 3.0) > 0.99
    assert st.psr(0.0, 100, 0.0, 3.0) == pytest.approx(0.5)
    short, long_ = st.min_track_record_length(0.3, 0, 3), st.min_track_record_length(0.1, 0, 3)
    assert short < long_ and st.min_track_record_length(-0.1, 0, 3) == math.inf
    assert st.required_sample_size(0.2) > st.required_sample_size(0.4)
    with pytest.raises(ValueError):
        st.required_sample_size(0)


def test_sign_flip_detects_edge_and_not_noise():
    rng = np.random.default_rng(3)
    assert st.sign_flip_pvalue(rng.normal(0.4, 1.0, 200)) < 0.01
    ps = [st.sign_flip_pvalue(np.random.default_rng(s).normal(0, 1, 200), B=499) for s in range(100, 160)]
    assert np.mean(np.array(ps) < 0.05) < 0.15  # ~5 % attendus, marge pour 60 tirages
    assert st.sign_flip_pvalue([1, 1]) == 1.0  # trop court


def test_null_resolution_and_sidak():
    assert st.sidak_alpha(0.10, 1) == pytest.approx(0.10)
    assert st.sidak_alpha(0.10, 50) < 0.003
    res = st.null_resolution(st.sidak_alpha(0.10, 50))
    assert res["evaluable"] and 1 / (res["B"] + 1) < st.sidak_alpha(0.10, 50)
    assert not st.null_resolution(1e-9)["evaluable"]  # impossible à franchir : signalé, jamais ignoré


def test_mc_paths_shapes_and_losing_streaks():
    r = np.array([1.0, -1.0] * 50)
    eq, dd, streak = st.mc_paths(r, 1.0, length=40, paths=200)
    assert eq.shape == (200, 40) and (dd >= 0).all() and (streak >= 0).all()
    eq0, dd0, _ = st.mc_paths([], 1.0, paths=5)
    assert eq0.shape == (5, 1) and not dd0.any()
    _, _, s_all_loss = st.mc_paths([-1.0] * 20, 1.0, length=10, paths=5)
    assert (s_all_loss == 10).all()


def test_reality_check_planted_vs_noise():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 1, (500, 8))
    planted = noise.copy()
    planted[:, 3] += 0.25
    assert st.reality_check(planted, B=500)["p"] < 0.05
    assert st.reality_check(planted, B=500)["best"] == 3
    assert st.reality_check(noise, B=500)["p"] > 0.05
    assert st.reality_check(noise[:10])["p"] is None
