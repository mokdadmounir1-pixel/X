import numpy as np
import pytest

from quantbot.stat import equity_formulas as f


def test_portfolio_cost_matches_the_published_formula_by_hand():
    w_prev = np.array([0.5, -0.5, 0.0]); w = np.array([0.25, -0.25, 0.5])
    assert f.portfolio_cost(w, w_prev) == pytest.approx(0.0005 * (0.25 + 0.25 + 0.5) + 0.0001 * 0.25)
    assert f.portfolio_cost(w, w) == pytest.approx(0.0001 * 0.25) and f.portfolio_cost(np.zeros(3), np.zeros(3)) == 0.0


def test_gross_exposure_is_one_and_zero_vector_is_unchanged():
    w = f.normalize_gross([2.0, -1.0, 1.0]); assert np.abs(w).sum() == pytest.approx(1.0) and w[0] == pytest.approx(0.5)
    assert (f.normalize_gross([0, 0]) == 0).all()


def test_residual_is_what_exceeds_the_common_component():
    assert f.residual_return(0.03, [1.0, 0.5], [0.02, 0.02]) == pytest.approx(0.03 - 0.03)
    assert f.residual_return(-0.01, [1.0], [0.02]) == pytest.approx(-0.03)


def test_rvol_requires_exactly_14_clean_sessions():
    assert f.rvol(300.0, [100.0] * 14) == pytest.approx(3.0)
    assert np.isnan(f.rvol(300.0, [100.0] * 13)) and np.isnan(f.rvol(300.0, [100.0] * 13 + [np.nan])) and np.isnan(f.rvol(1.0, [0.0] * 14))


def test_stock_in_play_filters_and_top_selection_is_deterministic():
    ok = dict(open_price=20.0, avg_volume_14=2e6, atr_14=1.0, open_volume=5e4, avg_open_volume_14=4e4)
    assert f.stock_in_play(**ok)
    for k, bad in (("open_price", 4.0), ("avg_volume_14", 9e5), ("atr_14", 0.4), ("open_volume", 3e4)):
        assert not f.stock_in_play(**{**ok, k: bad})
    r = {f"S{i}": float(i) for i in range(30)}; r["NAN"] = float("nan"); r["TIE_A"] = 29.0
    top = f.top_by_rvol(r, 20); assert len(top) == 20 and top[0] == "S29" and top[1] == "TIE_A" and "NAN" not in top


def test_stop_quantity_and_cost_in_r_show_why_tight_stops_make_costs_heavy():
    d = f.orb_stop_distance(2.0); assert d == pytest.approx(0.20)
    assert f.max_quantity(100.0, d) == pytest.approx(500.0) and f.max_quantity(100.0, 0.0) == 0.0
    c = 2 * 0.0035; assert f.cost_in_r(c, d) == pytest.approx(0.035)
    assert f.cost_in_r(c, 0.02) == pytest.approx(10 * f.cost_in_r(c, 0.20)) and f.cost_in_r(c, 0.0) == float("inf")


def test_expectancy_decomposition():
    assert f.expectancy(0.4, 2.0, -1.0, 0.1) == pytest.approx(0.4 * 2.0 - 0.6 * 1.0 - 0.1)
    assert f.expectancy(0.7, 0.5, 1.5, 0.0) < 0                          # un taux de réussite élevé ne suffit pas
