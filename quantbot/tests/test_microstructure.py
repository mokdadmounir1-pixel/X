import numpy as np
import pandas as pd
import pytest

from quantbot.strategies import apex_composite as ac, intermarket_telemetry as im, order_flow_ofi as of, stop_hunt_engine as sh
from quantbot.strategies.events import atr_series
from tests.test_apex import _trending


def test_ofi_l1_signs_and_known_values():
    e = of.ofi_l1([100, 100, 101], [101, 101, 102], [10, 15, 12], [10, 10, 9])
    assert e[0] == 0.0 and e[1] == 5.0                                              # bid inchangé : +delta de taille ; ask inchangé : contribution nette nulle
    up = of.ofi_l1([100, 101], [101, 102], [5, 5], [5, 5]); dn = of.ofi_l1([101, 100], [102, 101], [5, 5], [5, 5])
    assert up[1] > 0 > dn[1]                                                       # prix qui montent = pression acheteuse
    i = of.imbalance(np.r_[0, np.full(50, 100.0)], 10, np.full(51, 10.0)); assert np.nanmax(np.abs(i)) <= 1


def test_tick_proxy_and_absorption_proxy_are_bounded_and_directional():
    bid = np.cumsum(np.r_[0, np.ones(30), -np.ones(10)]) + 100; t = of.tick_flow_imbalance(bid, bid + 0.1, 10)
    assert t[25] == 1.0 and t[-1] < 0 and np.abs(t).max() <= 1
    df = _trending(3000); atr = atr_series(df, 14); a = of.absorption_score(df, atr); a = a[~np.isnan(a)]; assert a.min() >= 0 and a.max() <= 1
    d2 = df.copy(); d2.iloc[2500, d2.columns.get_loc("volume")] = 1000.0; d2.iloc[2500, d2.columns.get_loc("high")] = d2.iloc[2500].open * 1.00001; d2.iloc[2500, d2.columns.get_loc("low")] = d2.iloc[2500].open * 0.99999
    assert of.absorption_score(d2, atr_series(d2, 14))[2500] > 0.9
    sc = of.release_direction_score(d2, of.absorption_score(d2, atr_series(d2, 14)), atr_series(d2, 14)); assert np.nanmax(np.abs(sc)) <= 1


def test_lead_lag_detects_a_planted_lead_and_reports_nothing_on_independent_noise():
    rng = np.random.default_rng(0); x = rng.normal(0, 0.001, 20000); g = 0.5 * np.r_[0, x[:-1]] + rng.normal(0, 0.001, 20000)
    idx = pd.date_range("2024-01-01", periods=20000, freq="15min"); gc, xc = pd.Series(100 * np.exp(np.cumsum(g)), idx), pd.Series(100 * np.exp(np.cumsum(x)), idx)
    r = im.lead_lag(gc, xc); assert r.loc[1, "t"] > 20 and abs(r.loc[2, "t"]) < 4
    y = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.001, 20000))), idx); assert abs(im.lead_lag(gc, y).loc[1, "t"]) < 4


def test_composite_geometric_missing_pillars_excluded_never_filled():
    full = ac.composite({"S": 0.9, "G": 0.8, "I": 0.7, "T": 0.6}, +1); part = ac.composite({"S": 0.9, "G": None, "I": None, "T": 0.6}, +1)
    assert full["missing"] == [] and part["missing"] == ["G", "I"] and part["used"] == ["S", "T"] and 0 < part["omega"] < 1
    assert ac.composite({"S": 0.9, "I": -0.8}, +1)["omega"] == 0 and ac.composite({"S": 0.9, "I": -0.8}, -1)["omega"] > 0     # un pilier opposé annule le setup, pas de compensation


def test_stop_hunt_events_causal_post_sweep_only():
    rng = np.random.default_rng(1); n = 4000; c = 2000 + np.cumsum(rng.normal(0, 1.0, n)); o = np.r_[c[0], c[:-1]]; h = np.maximum(o, c) + abs(rng.normal(0, 0.4, n)); l = np.minimum(o, c) - abs(rng.normal(0, 0.4, n))
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 100.0}, index=pd.date_range("2024-01-01", periods=n, freq="15min"))
    full = sh.events(df); cut = 3000; part = sh.events(df.iloc[:cut]); k = lambda ev: [(e.ts, e.direction, round(e.stop, 6)) for e in ev]
    assert k([e for e in full if e.ts < df.index[cut - 1]]) == k([e for e in part if e.ts < df.index[cut - 1]])
    for e in full:
        px = df.close[e.ts]; assert abs(e.target - px) / abs(px - e.stop) == pytest.approx(3.0) and 0.5 <= e.meta["S"] <= 1.0 and 7 <= e.ts.hour < 17
    lv = sh.pool_score(np.array([2000.0, 2000.1, 2000.05, 2010.0]), 1.0, sh.PARAMS); assert lv[0] > 0 and abs(lv[1] - 2000.05) < 0.1


def test_micro_price_pulls_toward_thin_side_and_never_invents_without_sizes():
    mp = of.micro_price([100.0, 100.0, 100.0], [101.0, 101.0, 101.0], [1.0, 9.0, 0.0], [9.0, 1.0, 0.0])
    assert mp[0] < 100.5 < mp[1] and abs(mp[0] - 100.1) < 1e-9 and np.isnan(mp[2])     # tailles bid fines -> micro-prix vers le bid ; rien sans tailles


def test_toxicity_proxy_and_continuous_pause_factor():
    one_way = np.cumsum(np.ones(40)) + 100; mixed = 100 + np.cumsum(np.tile([1.0, -1.0], 20))
    assert of.aggression_ratio(one_way, one_way + .1)[-1] == 1.0 and of.aggression_ratio(mixed, mixed + .1)[-1] < 0.2
    f = [of.toxicity_pause(r) for r in (0.5, 0.8, 0.85, 0.9, 1.0)]; assert f[0] == 1.0 and f == sorted(f, reverse=True) and f[-1] == 0.0 and 0 < f[2] < 1


def test_live_store_manifest_append_is_linear_not_quadratic_and_chain_stays_valid(tmp_path):
    import time
    from quantbot.data.live_store import LiveBarStore
    def run(n, sub):
        st = LiveBarStore(tmp_path / sub); t0 = time.perf_counter()
        for i in range(n):
            st._log({"kind": "x", "i": i})
        return st, time.perf_counter() - t0
    _, t_small = run(400, "a"); st, t_big = run(1600, "b")             # x4 écritures : ~x4 si linéaire, ~x16 si quadratique (mesure relative : indépendante de la vitesse du disque)
    assert st.verify() and t_big < 9.0 * max(t_small, 1e-3)
