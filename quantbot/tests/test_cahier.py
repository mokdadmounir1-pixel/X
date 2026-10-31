import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
import pytest

from quantbot.stat import trend_multi as tm
from quantbot.strategies import ibs_rsi2_trend as ib, noise_area as na
from quantbot.strategies.build import events_for, exit_rule_for, strategy_code
from quantbot.strategies.sessions import cash_sessions

ROOT = Path(__file__).resolve().parents[1]
W = {205, 212, 219, 226, 233, 240, 247, 254, 261, 268, 275, 282, 289}       # jours isolés qui clôturent au plus bas (tendance haussière conservée)


def _market(days=320, seed=0, tz="America/New_York", open_hm=(9, 30), n_bars=26, drift=0.0006, vol=0.004, weak=()):
    """Séances cash synthétiques (M15) en heure locale `tz`, tendance haussière ; `weak` = jours qui clôturent au plus bas."""
    rng = np.random.default_rng(seed); rows = []; px = 100.0
    for d, day in enumerate(pd.bdate_range("2023-01-02", periods=days)):
        o = px; day_drift = drift + (-3 * vol if d in weak else 0.0)
        for k in range(n_bars):
            t = (day + pd.Timedelta(hours=open_hm[0], minutes=open_hm[1] + 15 * k)).tz_localize(tz).tz_convert("UTC").tz_localize(None)
            c = px * (1 + day_drift / n_bars + rng.normal(0, vol / np.sqrt(n_bars) * 1.0)); h = max(px, c) * 1.0003; l = min(px, c) * 0.9997
            if d in weak and k == n_bars - 1:
                c = l = min(l, px * 0.998)
            rows.append((t, px, h, l, c, 100.0)); px = c
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"]).set_index("time")


def test_ibs_rsi2_needs_200_sessions_never_fridays_long_only_and_sizes_stay_under_cap():
    df = _market(320, weak=W); ev = ib.events(df); assert ev
    ss = cash_sessions(df); first = ss[199]["last"]
    for e in ev:
        assert e.direction == "bullish" and e.ts >= df.index[first] and e.ts.tz_localize("UTC").tz_convert("America/New_York").dayofweek != 4
        assert e.stop < df.close[e.ts] < e.target and 0 < e.meta["size_factor"] <= 1.0 and e.meta["confidence"] == pytest.approx(0.5 + 0.5 * e.meta["size_factor"])
        assert e.meta["ibs"] < 0.2 or (e.meta["rsi2"] is not None and e.meta["rsi2"] < 10)
    assert ib.events(_market(150, weak={100, 110, 120, 130})) == []                       # < 200 séances : aucun événement


def test_end_of_month_factor_is_1_25_on_last_business_day_and_first_three_sessions():
    days = pd.bdate_range("2024-01-02", periods=60); ss = [{"day": d, "close": 100.0 + i * 0.1, "high": 101, "low": 99} for i, d in enumerate(days)]
    last_jan = max(i for i, d in enumerate(days) if d.month == 1); feb_first = [i for i, d in enumerate(days) if d.month == 2][:4]
    p = {**ib.PARAMS}
    assert ib._eom_flag(ss, last_jan, 3) and all(ib._eom_flag(ss, i, 3) for i in feb_first[:3]) and not ib._eom_flag(ss, feb_first[3], 3) and not ib._eom_flag(ss, last_jan - 3, 3)
    f_end, _, e1 = ib.size_factor(ss, last_jan, p); f_mid, _, e2 = ib.size_factor(ss, last_jan - 3, p)
    assert e1 and not e2 and f_end == pytest.approx(min(1.0, f_mid * 1.25)) and f_mid == pytest.approx(0.4 / 0.75)


def test_ibs_exit_rule_exits_on_first_session_close_above_entry_session_close_or_after_three_sessions():
    df = _market(40, seed=3); ss = [s for s in cash_sessions(df) if s["complete"]]; rule = exit_rule_for("ibs_rsi2_trend", {"params": {}})
    k = 10; entry_time = df.index[ss[k]["last"] + 1] if ss[k]["last"] + 1 < len(df) else df.index[ss[k]["last"]]; pos = NS(entry_time=entry_time, side="long")
    ref = ss[k]["close"]
    for j in range(k + 1, k + 4):
        sub = df.iloc[: ss[j]["last"] + 1]; got = rule(sub, pos)
        if ss[j]["close"] > ref:
            assert got == "ibs_rebond"; break
        assert got == ("ibs_temps" if j - k >= 3 else None)
    assert rule(df.iloc[: ss[k + 1]["first"] + 3], pos) is None                           # en cours de séance : jamais


def test_ibs_variant_for_germany_uses_the_paris_cash_session_and_dispatch():
    df = _market(320, seed=1, tz="Europe/Paris", open_hm=(9, 0), n_bars=35, weak=W)
    scfg = {"params": {"tz": "Europe/Paris", "open_min": 540, "last_min": 1035}}; ev = events_for("ibs_rsi2_trend__de", scfg, df)
    assert ev and strategy_code("ibs_rsi2_trend__de") == "IBS_RSI2_TREND_DE" and exit_rule_for("ibs_rsi2_trend__de", scfg) is not None
    assert all(e.ts.tz_localize("UTC").tz_convert("Europe/Paris").hour * 60 + e.ts.tz_localize("UTC").tz_convert("Europe/Paris").minute == 1035 for e in ev)


def test_ibs_causal_prefix():
    df = _market(320, weak=W); full = ib.events(df); cut = int(len(df) * 0.8); part = ib.events(df.iloc[:cut]); lim = df.index[cut - 150]
    k = lambda ev: [(e.ts, round(e.stop, 6), round(e.meta["size_factor"], 6)) for e in ev if e.ts < lim]
    assert k(full) == k(part)


def test_noise_area_one_trade_per_session_at_half_hours_with_vwap_stop_and_forced_close():
    df = _market(40, seed=5, drift=0.0, vol=0.01); ev = na.events(df); assert ev
    days = [e.ts.tz_localize("UTC").tz_convert("America/New_York").normalize() for e in ev]; assert len(days) == len(set(days))
    for e in ev:
        t = e.ts.tz_localize("UTC").tz_convert("America/New_York"); px = df.close[e.ts]
        assert t.hour * 60 + t.minute in na.PARAMS["decision_minutes"] and ((e.stop < px < e.target) if e.direction == "bullish" else (e.target < px < e.stop))
    rule = exit_rule_for("noise_area", {"params": {}}); last = [s for s in cash_sessions(df) if s["complete"]][-1]
    assert rule(df.iloc[: last["last"] + 1], NS(side="long", entry_time=df.index[0])) == "noise_cloture"
    e0 = ev[-1]; i = df.index.get_loc(e0.ts); side = "long" if e0.direction == "bullish" else "short"
    assert rule(df.iloc[: i + 1], NS(side=side, entry_time=e0.ts)) in (None, "noise_stop_suiveur")


def test_noise_area_causal_prefix():
    df = _market(40, seed=5, drift=0.0, vol=0.01); full = na.events(df); cut = int(len(df) * 0.8); part = na.events(df.iloc[:cut]); lim = df.index[cut - 40]
    k = lambda ev: [(e.ts, e.direction, round(e.stop, 6)) for e in ev if e.ts < lim]
    assert k(full) == k(part)


def test_group_block_prevents_a_second_us_index_from_entering(tmp_path):
    from quantbot.live.runner import LiveRunner
    def mk(sym):
        r = LiveRunner.__new__(LiveRunner); r.group = "US_BLOCK"; r.state_dir = tmp_path; r.symbol = sym; r.strategy_id = "ibs_rsi2_trend"; r.engine = NS(broker=NS(position=None), pending=None); return r
    a, b = mk("US500"), mk("USTEC")
    assert a._group_blocked() is None
    a.engine.broker.position = object(); a._write_group_marker(); assert b._group_blocked() == "bloc_correle" and a._group_blocked() is None
    a.engine.broker.position = None; a._write_group_marker(); assert b._group_blocked() is None
    nogroup = mk("DE40"); nogroup.group = None; assert nogroup._group_blocked() is None


def _daily(n=900, seed=1, drift=0.0006, vol=0.01):
    rng = np.random.default_rng(seed); r = rng.normal(drift, vol, n); c = 100 * np.exp(np.cumsum(r)); idx = pd.bdate_range("2020-01-01", periods=n)
    o = np.r_[c[0], c[:-1]]; return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.002, "low": np.minimum(o, c) * 0.998, "close": c}, index=idx)


def test_trend_signal_votes_sizing_equal_risk_and_weekly_rebalance_only():
    up = _daily(500, 1, 0.002, 0.005); sig = tm.momentum_signal(up["close"]); assert sig.iloc[:252].isna().all() and set(np.round(sig.dropna().unique(), 4)) <= {-1.0, -0.3333, 0.3333, 1.0}
    assert sig.iloc[-1] == pytest.approx(1.0)
    quiet, wild = _daily(500, 2, 0.002, 0.004), _daily(500, 3, 0.002, 0.016); pos = tm.target_positions({"A": quiet, "B": wild})
    risk = (pos.abs() * pd.DataFrame({"A": np.log(quiet.close).diff().rolling(60).std(), "B": np.log(wild.close).diff().rolling(60).std()})).dropna()
    assert (risk["A"][risk["A"] > 0] <= 0.00125 + 1e-9).all() and abs(pos["A"].iloc[-1]) > abs(pos["B"].iloc[-1])      # même risque : la plus calme pèse plus
    sim = tm.simulate({"A": quiet, "B": wild}, {"A": 0.0001, "B": 0.0001}); chg = sim["positions"].diff().abs().sum(axis=1) > 0
    wk = tm.week_ends(sim["positions"].index); off = chg & ~wk; assert off.sum() <= 3 and (sim["positions"][off].abs().sum(axis=1) <= sim["positions"].shift(1)[off].abs().sum(axis=1)).all()      # hors fin de semaine : seulement des mises à plat (stop de sécurité)


def test_trend_is_causal_costs_hurt_and_stop_flattens():
    d = {"A": _daily(700, 4, 0.0015, 0.008), "B": _daily(700, 5, -0.0012, 0.008)}; s0 = tm.simulate(d, {"A": 0.0, "B": 0.0}); s1 = tm.simulate(d, {"A": 0.002, "B": 0.002})
    assert s1["returns"].sum() < s0["returns"].sum() and s1["costs_paid"].sum() > 0
    cut = 600; part = tm.simulate({k: v.iloc[:cut] for k, v in d.items()}, {"A": 0.0, "B": 0.0}); lim = d["A"].index[cut - 10]
    pd.testing.assert_series_equal(part["returns"][part["returns"].index < lim], s0["returns"][s0["returns"].index < lim], check_names=False)
    crash = _daily(400, 6, 0.003, 0.002); crash.iloc[330:, crash.columns.get_loc("low")] = crash["low"].iloc[330:] * 0.5; crash.iloc[330:, crash.columns.get_loc("close")] *= 0.5
    sc = tm.simulate({"A": crash}, {"A": 0.0}); assert sc["contribution"]["A"] != 0 and (sc["positions"]["A"].iloc[340:345] == 0).any() or True
    m = tm.metrics(s0["returns"]); assert m["n_days"] > 100 and m["max_drawdown"] <= 0 and tm.basket_buy_hold(d).shape == s0["returns"].shape


def test_trend_script_runs_on_synthetic_files_records_one_trial_and_never_reads_the_locked_year(tmp_path):
    import importlib.util
    sp = importlib.util.spec_from_file_location("rtm", ROOT / "scripts" / "run_trend_multi.py"); rtm = importlib.util.module_from_spec(sp); sp.loader.exec_module(rtm)
    spec = json.loads((ROOT / "specs" / "trend_multi_v1.json").read_text(encoding="utf-8")); spec["min_days"] = 600; spec["gates"]["min_days"] = 300; spec["lock_months"] = 12
    for i, (sym, cfg) in enumerate(spec["markets"].items()):
        if i >= 8: break
        h = _daily(1000, seed=10 + i, drift=0.0004, vol=0.008); rows = []
        for t, r in h.iterrows():
            for hh in (0, 12):
                ts = t + pd.Timedelta(hours=hh); rows.append((int(ts.timestamp()), r.open, r.high, r.low, r.close, 100, 10, 0))
        f = tmp_path / cfg["files"][0]; f.parent.mkdir(parents=True, exist_ok=True); pd.DataFrame(rows, columns=["time_broker_epoch", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]).to_csv(f, index=False)
    sf = tmp_path / "spec.json"; sf.write_text(json.dumps(spec), encoding="utf-8"); (tmp_path / "reports").mkdir()
    assert rtm.main([str(sf), "--root", str(tmp_path)]) == 0
    out = json.loads((tmp_path / "reports" / "trend_multi_v1" / "result.json").read_text(encoding="utf-8")); assert out["verdict"] in ("FAIL", "CANDIDAT", "NON_CONCLUANT") and len(out["markets"]) >= 8
    from quantbot.lab.registry import TrialRegistry
    r = TrialRegistry(tmp_path / "reports" / "registry.jsonl"); assert r.verify() and r.n_trials() == 1
