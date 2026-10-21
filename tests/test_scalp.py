import numpy as np
import pandas as pd
import pytest
from ftmo_algo.data.synth import make_series
from ftmo_algo.engine.news import NewsCalendar
from ftmo_algo.scalp.algos import SCALP_ALGOS, SCALP_EXITS, delay_signals
from ftmo_algo.scalp.costs import cost_report
from ftmo_algo.scalp.ctx import ScalpCtx
from ftmo_algo.scalp.pipeline import sim_scalp

M1 = make_series("US500", years=0.3, seed=3, step_min=1)
NEWS = NewsCalendar.default(M1.index[0], M1.index[-1] + pd.Timedelta(days=60))


def test_default_m5_generator_unchanged_by_step_parameter():
    a = make_series("EURUSD", years=0.05, seed=1)
    b = make_series("EURUSD", years=0.05, seed=1, step_min=5)
    pd.testing.assert_frame_equal(a, b)


@pytest.mark.parametrize("name", list(SCALP_ALGOS))
def test_scalp_signals_on_prefix_identical_to_full_series(name):
    full = ScalpCtx("US500", M1, news=NEWS)
    k = int(len(M1) * 0.7)
    pre = ScalpCtx("US500", M1.iloc[:k], news=NEWS)
    a = SCALP_ALGOS[name]
    sf, sp = a.generate(full, a.default, SCALP_EXITS["s2"]), a.generate(pre, a.default, SCALP_EXITS["s2"])
    assert np.array_equal(sf.side[:k], sp.side)
    m = sp.side != 0
    assert np.allclose(sf.stop[:k][m], sp.stop[m], equal_nan=True)
    assert np.allclose(sf.target[:k][m], sp.target[m], equal_nan=True)


def test_future_data_cannot_change_past_scalp_context():
    full = ScalpCtx("US500", M1, news=NEWS)
    k = int(len(M1) * 0.6)
    bad = M1.copy()
    bad.iloc[k:, :4] = bad.iloc[k:, :4].to_numpy() * 3.1
    bad["high"] = bad[["open", "high", "close"]].max(axis=1)
    bad["low"] = bad[["open", "low", "close"]].min(axis=1)
    p = ScalpCtx("US500", bad, news=NEWS)
    z1, v1 = full.vwap_z(); z2, v2 = p.vwap_z()
    for x, y in ((full.atr, p.atr), (full.rt_cost, p.rt_cost), (z1, z2), (v1, v2)):
        assert np.allclose(x[:k], y[:k], equal_nan=True)


def test_delay_shifts_signals_by_one_bar_and_never_looks_ahead():
    ctx = ScalpCtx("US500", M1, news=NEWS)
    a = SCALP_ALGOS["orb_micro"]
    s = a.generate(ctx, a.default, SCALP_EXITS["s2"])
    d = delay_signals(s, 1)
    assert d.side[0] == 0 and np.array_equal(d.side[1:], s.side[:-1])
    assert (d.idx() > s.idx().min() - 1).all()


def test_costs_double_lowers_every_variant_expectancy():
    ctx = ScalpCtx("US500", M1, news=NEWS)
    a = SCALP_ALGOS["orb_micro"]
    s = a.generate(ctx, a.default, SCALP_EXITS["s2"])
    r1 = sim_scalp(ctx, s, 1.0).r.mean()
    r2 = sim_scalp(ctx, s, 2.0).r.mean()
    assert r2 < r1


def test_cost_report_breakeven_formula():
    rep = cost_report({"US500": M1})["US500"]["fenetres"]
    w = next(iter(rep.values()))["stop=1.0ATR"]
    c = w["cout_R"]
    assert abs(w["winrate_equilibre"]["RR2.0"] - (1 + c) / 3) < 1e-3
