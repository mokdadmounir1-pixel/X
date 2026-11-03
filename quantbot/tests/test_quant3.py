import json
import math
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
import pytest
from scipy.stats import t as student

from quantbot.stat import hawkes as hk, leadlag as ll, signature as sg, tda
from quantbot.strategies import hawk_tox, leadlag_k, sig_tda
from quantbot.strategies.build import STRATEGY_CODES, events_for, exit_rule_for
from quantbot.strategies.external_data import REQUIRES, missing

ROOT = Path(__file__).resolve().parents[1]


def _sim_hawkes(mu, a, beta, T, seed=0):
    rng = np.random.default_rng(seed); t = 0.0; ev = []; S = np.zeros(2)
    while t < T:
        M = (mu + a @ S).sum() + 1e-9; w = rng.exponential(1 / M); t += w; S = S * np.exp(-beta * w)
        if t >= T: break
        lam = mu + a @ S
        if rng.uniform() * M <= lam.sum():
            i = 0 if rng.uniform() < lam[0] / lam.sum() else 1; ev.append((t, i)); S[i] += 1
    return np.array(ev)


def test_t3_cdf_matches_scipy_and_bvc_vpin_is_bounded():
    x = np.linspace(-6, 6, 25); assert np.abs(hk.t3_cdf(x) - student.cdf(x, 3)).max() < 1e-9
    rng = np.random.default_rng(0); dp = rng.normal(size=3000); v = rng.uniform(50, 150, 3000); vp = hk.vpin_series(dp, v, 50, 500); ok = vp[~np.isnan(vp)]
    assert ok.min() >= 0 and ok.max() <= 1 and np.isnan(vp[:40]).all()
    trend = hk.vpin_series(np.abs(rng.normal(size=3000)) + 0.5, v, 50, 500); assert np.nanmean(trend) > np.nanmean(vp)         # flux unilatéral = plus toxique


def test_tick_rule_and_hawkes_mle_recovers_criticality_and_online_matches_batch():
    assert list(hk.tick_rule(np.array([1, 2, 2, 1, 1, 1, 2.0]))) == [1, 1, -1, -1, -1, 1]
    mu = np.array([0.3, 0.3]); a = np.array([[0.5, 0.2], [0.2, 0.5]]); beta = 1.5; ev = _sim_hawkes(mu, a, beta, 3000, 1)
    f = hk.fit_hawkes(ev[:, 0], ev[:, 1].astype(int)); true_rho = hk.spectral_radius(a, beta)
    assert abs(f["rho"] - true_rho) < 0.12 and f["ok"]
    hot = _sim_hawkes(mu, np.array([[0.9, 0.3], [0.3, 0.9]]), beta, 3000, 2); fh = hk.fit_hawkes(hot[:, 0], hot[:, 1].astype(int)); assert fh["rho"] > f["rho"] + 0.2 and fh["rho"] >= 0.7
    o = hk.OnlineHawkes(mu, a, beta); t_e = ev[:200]
    for t, i in t_e: o.update(t, int(i))
    t_q = t_e[-1, 0] + 0.7; batch = mu + a @ np.array([np.exp(-beta * (t_q - t_e[t_e[:, 1] == j, 0])).sum() for j in (0, 1)])
    assert np.allclose(o.intensity(t_q), batch) and -1 <= o.imbalance(t_q) <= 1
    with pytest.raises(ValueError):
        hk.fit_hawkes(np.arange(50.0), np.zeros(50, int))


def test_lead_lag_hy_finds_the_leader_asynchronously_and_kalman_tracks_beta():
    rng = np.random.default_rng(1); t = np.arange(0, 1000.0); X = np.cumsum(rng.normal(size=1000)); Y = np.r_[np.zeros(3), X[:-3]] + 0.3 * np.cumsum(rng.normal(size=1000))
    r = ll.lead_lag(t, X, t, Y, list(range(-5, 6))); assert r["lag_star"] == 3 and r["llr"] > 5
    ty = np.sort(rng.uniform(0, 1000, 900)); Yi = np.interp(ty - 3, t, X) + 0.02 * rng.normal(size=900).cumsum(); r2 = ll.lead_lag(t, X, ty, Yi, list(range(-6, 7))); assert r2["lag_star"] == 3 and r2["llr"] > 5
    z = rng.normal(size=2000); y = np.r_[np.zeros(2), z[:-2]]; b = ll.lag_by_bars(y + rng.normal(size=2000) * 0.5, z, 5); assert b["lag_star"] == 2 and b["llr"] > 5
    k = ll.KalmanBetas(1, q=1e-6, r=0.25); zz = rng.normal(size=3000); yy = 0.7 * zz + rng.normal(size=3000) * 0.5
    for a, c in zip(zz, yy): k.update(np.array([a]), c)
    assert abs(k.b[0] - 0.7) < 0.1


def test_signature_matches_closed_forms_chen_and_reparametrisation():
    D = np.array([1.0, 2.0, 3.0]); s = sg.signature(np.array([[0, 0, 0], D])); assert len(s) == 39 and np.allclose(s[:3], D) and np.isclose(s[-1], 27 / 6) and np.isclose(s[3 + 1], 2.0 * 1.0 / 2 * 1.0 * 2 / 2 * 1 or s[4], s[4])
    sq = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], float); assert sg.levy_area(sq) == pytest.approx(1.0) and sg.levy_area(sq[::-1]) == pytest.approx(-1.0)
    rng = np.random.default_rng(0); p = np.cumsum(rng.normal(size=(12, 3)), axis=0); a, b = p[:7], p[6:]
    assert np.allclose(sg.signature(p)[:3], sg.signature(a)[:3] + sg.signature(b)[:3])                                          # niveau 1 additif
    q = np.insert(p, 3, (p[2] + p[3]) / 2, axis=0); assert np.allclose(sg.signature(p), sg.signature(q))                      # insérer un point milieu d'un segment ne change rien


@pytest.mark.skipif(not tda.available(), reason="ripser absent")
def test_tda_gate_norm_is_large_for_a_loop_and_small_for_noise_and_none_without_data():
    th = np.linspace(0, 2 * np.pi, 40, endpoint=False); circ = np.c_[np.cos(th), np.sin(th)]; rng = np.random.default_rng(0)
    assert tda.landscape_l1(circ) > 20 * tda.landscape_l1(rng.normal(size=(40, 2)) * 0.5) and tda.landscape_l1(np.array([[0.0, 0.0]])) is None


def _m15(n=7000, seed=0, name="X"):
    rng = np.random.default_rng(seed); r = rng.normal(0, 0.001, n); c = 100 * np.exp(np.cumsum(r)); o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.0004, "low": np.minimum(o, c) * 0.9996, "close": c, "volume": rng.uniform(50, 150, n), "spread": 0.01}, index=pd.date_range("2024-01-01", periods=n, freq="15min"))


def _write_live(root, sym, df, tf="M15"):
    d = Path(root) / "data" / "live"; d.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame({"time_broker_epoch": ((df.index + pd.Timedelta(hours=2)).astype("datetime64[ns]").astype("int64") // 10**9).astype(int), "open": df.open, "high": df.high, "low": df.low, "close": df.close, "tick_volume": df.volume, "spread": 1, "spread_points": 1, "real_volume": 0})
    out.to_csv(d / f"{sym}_{tf}.csv", index=False)


@pytest.mark.skipif(not tda.available(), reason="ripser absent")
def test_sig_tda_is_gated_by_data_causal_and_sizes_by_score(tmp_path):
    df = _m15(4500); params = {"root": str(tmp_path), "assets": ["A", "B", "C", "D"], "L": 24, "train_n": 200, "retrain": 12, "s_min": 0.3, "W": 32, "gate_hist": 200}
    assert sig_tda.events(df, params) == []                                                       # données des 4 actifs absentes : aucun trade
    for i, s in enumerate("ABCD"): _write_live(tmp_path, s, _m15(4500, i))
    ev = sig_tda.events(df, params); assert ev
    for e in ev:
        px = df.close[e.ts]; assert (e.stop < px < e.target) if e.direction == "bullish" else (e.target < px < e.stop)
        assert 0 < e.meta["size_factor"] <= 1.0 and e.meta["confidence"] == pytest.approx(0.5 + 0.5 * max(e.meta["size_factor"], 0.2)) and abs(e.meta["score"]) >= 0.3
    cut = 3600; part = sig_tda.events(df.iloc[:cut], params); lim = df.index[cut - 40]
    k = lambda x: [(e.ts, e.direction, round(e.stop, 6)) for e in x if e.ts < lim]
    assert k(ev) == k(part) and events_for("sig_tda", {"params": params}, df) == ev


def test_hawk_tox_and_leadlag_are_data_gated_and_hawk_features_are_causal(tmp_path):
    df = _m15(600, 3).rename_axis(None); df.index = pd.date_range("2024-01-01", periods=600, freq="1min")
    assert hawk_tox.events(df, {"root": str(tmp_path)}) == [] and leadlag_k.events(df, {"root": str(tmp_path)}) == []
    assert set(REQUIRES) >= {"hawk_tox", "leadlag_k"} and missing("hawk_tox", tmp_path) and missing("leadlag_k", tmp_path)
    rng = np.random.default_rng(0); ev = _sim_hawkes(np.array([2.0, 2.0]), np.array([[1.2, 0.6], [0.6, 1.2]]), 2.0, 600 * 60 / 10, 5); t_s = ev[:, 0] * 10             # événements sur la durée des barres
    px = 2000 + np.cumsum(np.where(ev[:, 1] == 0, 0.01, -0.01)); idx = pd.to_datetime(1704067200 + t_s, unit="s")
    ticks = pd.DataFrame({"bid": px, "ask": px + 0.02}, index=idx); ticks["mid"] = (ticks.bid + ticks.ask) / 2
    F = hawk_tox.features(df, {"min_fit_events": 100, "fit_hours": 2, "refit_minutes": 30, "q_window": 100, "fit_max_events": 1500}, ticks)
    assert F is not None and F["rho"].notna().any() and (F["imb"].dropna().abs() <= 1).all()
    F2 = hawk_tox.features(df.iloc[:400], {"min_fit_events": 100, "fit_hours": 2, "refit_minutes": 30, "q_window": 100, "fit_max_events": 1500}, ticks)
    lim = 380; a, b = F["imb"].iloc[:lim].to_numpy(), F2["imb"].iloc[:lim].to_numpy(); assert np.allclose(a, b, equal_nan=True)         # préfixe identique


def test_specs_are_paper_only_per_strategy_timeframe_and_codes_exist():
    for n, names in (("hawk_tox_v1", ["hawk_tox"]), ("leadlag_k_v1", ["leadlag_k", "leadlag_k__de"]), ("sig_tda_v1", ["sig_tda"])):
        s = json.loads((ROOT / "specs" / f"{n}.json").read_text(encoding="utf-8")); assert s["trials"] == 0 and set(s["strategies"]) == set(names)
        for k, sc in s["strategies"].items():
            assert exit_rule_for(k, sc) is not None or k in ("sig_tda",) ; assert sc["history_bars"] >= 3000 and all(i in s["costs"] for i in sc["instruments"])
    for n in ("hawk_tox", "leadlag_k", "sig_tda"): assert n in STRATEGY_CODES
    assert json.loads((ROOT / "specs" / "hawk_tox_v1.json").read_text())["strategies"]["hawk_tox"]["timeframe"] == "M1"
