import numpy as np
import pandas as pd
import pytest

from quantbot.lab import battery as bt
from quantbot.lab.stats import reality_check


def ny_to_utc(naive_ny: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return naive_ny.tz_localize("America/New_York", nonexistent="shift_forward", ambiguous="NaT").tz_convert("UTC").tz_localize(None)


def make_m15(days=400, seed=0, im_edge=0.0, sigma=0.0006):
    """M15 24 h, jours ouvrés, indexé en UTC. Effet planté : rendement des 2 dernières barres (15:30-16:00 NY) = edge x signe du rendement (veille 16:00 -> 10:00)."""
    rng = np.random.default_rng(seed)
    idx_ny = pd.date_range("2023-01-02", periods=days * 96, freq="15min")
    idx_ny = idx_ny[idx_ny.dayofweek < 5]
    ret = rng.normal(0, sigma, len(idx_ny))
    hm = idx_ny.hour * 60 + idx_ny.minute
    if im_edge:
        last = np.flatnonzero((hm == 15 * 60 + 30) | (hm == 15 * 60 + 45))
        for k in range(0, len(last), 2):
            i0 = last[k]
            day_start = np.flatnonzero((idx_ny.normalize() == idx_ny[i0].normalize()) & (hm == 0))
            prev = max(0, int(day_start[0]) - 8) if len(day_start) else 0
            sig = np.sign(ret[prev:np.flatnonzero((idx_ny.normalize() == idx_ny[i0].normalize()) & (hm == 9 * 60 + 45))[0] + 1].sum())
            ret[i0:i0 + 2] += sig * im_edge / 2
    close = 100 * np.exp(np.cumsum(ret)); open_ = np.concatenate(([100.0], close[:-1]))
    df = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.0001, "low": np.minimum(open_, close) * 0.9999,
                       "close": close, "volume": 1.0}, index=idx_ny)
    df.index = ny_to_utc(df.index)
    return df[df.index.notna()]


def test_price_slot_falls_back_to_previous_bar_close_when_slot_bar_is_missing():
    df = make_m15(20)
    p_full = bt.session_prices(df)
    ny = df.index.tz_localize("UTC").tz_convert(bt.TZ)
    drop = (ny.hour == 16) & (ny.minute == 0)
    p_drop = bt.session_prices(df[~drop])
    assert p_drop["1600"].notna().mean() > 0.99               # le créneau reste défini sans la barre de 16:00
    prev_close = df[(ny.hour == 15) & (ny.minute == 45)]["close"]
    assert set(np.round(p_drop["1600"].dropna().to_numpy()[:5], 8)) <= set(np.round(prev_close.to_numpy(), 8))


def test_newey_west_is_more_conservative_than_naive_on_autocorrelated_data():
    rng = np.random.default_rng(0)
    e = rng.normal(0, 1, 3000); x = np.zeros(3000)
    for i in range(1, 3000):
        x[i] = 0.7 * x[i - 1] + e[i]
    x += 0.05
    naive = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    assert abs(bt.newey_west_t(x, 10)) < abs(naive)
    iid = rng.normal(0, 1, 5000)
    assert abs(bt.newey_west_t(iid)) < 3.5 and bt.newey_west_t([1, 2]) == 0.0


def test_alpha_regression_recovers_planted_alpha_and_beta():
    rng = np.random.default_rng(1)
    b = rng.normal(0, 0.01, 2000)
    y = 0.0004 + 0.8 * b + rng.normal(0, 0.005, 2000)
    r = bt.alpha_vs_benchmark(y, b)
    assert r["beta"] == pytest.approx(0.8, abs=0.05) and r["alpha"] == pytest.approx(0.0004, abs=0.0004) and r["t_alpha"] > 2
    pure_beta = 1.0 * b + rng.normal(0, 0.001, 2000)
    assert abs(bt.alpha_vs_benchmark(pure_beta, b)["t_alpha"]) < 3   # simple exposition au marché : alpha non significatif


def test_intraday_momentum_finds_a_planted_effect_and_not_noise():
    cost = 2e-5
    planted = bt.HYPOTHESES["intraday_momentum"](bt.session_prices(make_m15(500, seed=3, im_edge=0.0012)), cost)
    s = bt.summarize(planted.net, planted.bh)
    assert s["mean_bps"] > 5 and s["t_nw"] > 4 and s["bh_t_alpha"] > 3
    null = bt.HYPOTHESES["intraday_momentum"](bt.session_prices(make_m15(500, seed=4)), cost)
    assert abs(bt.summarize(null.net, null.bh)["t_nw"]) < 3.5


def test_costs_are_charged_per_trade_and_double_costs_hurt():
    p = bt.session_prices(make_m15(300, seed=5))
    a = bt.HYPOTHESES["intraday_momentum"](p, 1e-4); b = bt.HYPOTHESES["intraday_momentum"](p, 2e-4)
    n = len(a.net)
    assert (a.gross.sum() - a.net.sum()) == pytest.approx(1e-4 * a.n_trades, rel=1e-6)
    assert b.net.mean() < a.net.mean() and n > 200
    ov = bt.HYPOTHESES["overnight_drift"](p, 1e-4)
    assert (ov.gross - ov.net).round(12).eq(1e-4).all()  # un aller-retour par nuit


@pytest.mark.parametrize("name", ["tsmom_20", "tsmom_60", "reversal_1d"])
def test_daily_signals_do_not_look_ahead(name):
    df = make_m15(300, seed=6)
    full = bt.HYPOTHESES[name](bt.session_prices(df), 1e-4).net
    cut = df.index[int(len(df) * 0.6)]
    part = bt.HYPOTHESES[name](bt.session_prices(df[df.index < cut]), 1e-4).net
    common = part.index[:-3]
    assert len(common) > 100 and np.allclose(full.reindex(common).to_numpy(), part.reindex(common).to_numpy())
    altered = df.copy(); altered.loc[altered.index >= cut, ["open", "high", "low", "close"]] *= 1.7
    alt = bt.HYPOTHESES[name](bt.session_prices(altered), 1e-4).net
    assert np.allclose(full.reindex(common).to_numpy(), alt.reindex(common).to_numpy())


def test_reality_check_over_a_battery_with_one_planted_effect():
    rng = np.random.default_rng(2)
    d = rng.normal(0, 0.01, (600, 14)); d[:, 5] += 0.0012
    assert reality_check(d, B=500)["p"] < 0.1 and reality_check(rng.normal(0, 0.01, (600, 14)), B=500)["p"] > 0.1
