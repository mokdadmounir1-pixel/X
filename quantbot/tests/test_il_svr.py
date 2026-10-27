import numpy as np
import pandas as pd
import pytest

from quantbot.strategies import il_svr
from quantbot.strategies.build import events_for, strategy_code


def _idx(n=9000, seed=0):
    rng = np.random.default_rng(seed); c = 15000 + np.cumsum(rng.normal(0, 8, n)); o = np.r_[c[0], c[:-1]]; h = np.maximum(o, c) + abs(rng.normal(0, 4, n)); l = np.minimum(o, c) - abs(rng.normal(0, 4, n))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.integers(50, 500, n).astype(float)}, index=pd.date_range("2024-01-01", periods=n, freq="15min"))


def test_events_only_in_the_two_utc_windows_after_the_first_hour_with_valid_levels():
    df = _idx(); ev = il_svr.events(df, {"omega_min": 0.15}); assert ev
    for e in ev:
        hr = e.ts.hour + e.ts.minute / 60; assert (9.0 <= hr < 10.5) or (14.5 <= hr < 16.0)                        # jamais dans la première heure ni hors fenêtre
        px = df.close[e.ts]; assert (e.stop > px > e.target) if e.direction == "bearish" else (e.target > px > e.stop)
        assert abs(e.target - px) / abs(e.stop - px) >= 2.0 - 1e-9 and 0 <= e.meta["omega"] <= 1


def test_causality_prefix_equality_and_mirror_symmetry():
    df = _idx(); cut = 6000; full = il_svr.events(df, {"omega_min": 0.15}); part = il_svr.events(df.iloc[:cut], {"omega_min": 0.15})
    k = lambda ev: [(e.ts, e.direction, round(e.stop, 6)) for e in ev]
    assert k([e for e in full if e.ts < df.index[cut - 1]]) == k([e for e in part if e.ts < df.index[cut - 1]])
    M = 30000.0; m = pd.DataFrame({"open": M - df.open, "high": M - df.low, "low": M - df.high, "close": M - df.close, "volume": df.volume}, index=df.index)
    flip = {"bullish": "bearish", "bearish": "bullish"}; a = {e.ts: flip[e.direction] for e in full}; b = {e.ts: e.direction for e in il_svr.events(m, {"omega_min": 0.15})}
    # le miroir inverse aussi le signe du CVD (clôture haute <-> basse) : les signaux coïncident aux mêmes barres
    common = set(a) & set(b); assert len(common) >= 0.8 * max(len(a), len(b)) and all(a[t] == b[t] for t in common)


def test_dispatch_code_and_spec_declares_limits():
    df = _idx(); assert events_for("il_svr", {"params": {"omega_min": 0.15}}, df) == il_svr.events(df, {"omega_min": 0.15}) and strategy_code("il_svr") == "IL_SVR_INDEX"
    import json, pathlib
    sp = json.loads((pathlib.Path(__file__).resolve().parents[1] / "specs" / "il_svr_v1.json").read_text(encoding="utf-8")); assert sp["trials"] == 1 and "deux temps" in sp["strategies"]["il_svr"]["note"]
