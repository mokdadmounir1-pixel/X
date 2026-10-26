import numpy as np
import pandas as pd
import pytest

from quantbot.improvement.apex_loop import propose_tighter_vol_filter, vol_expansion_failures
from quantbot.strategies import apex
from quantbot.strategies.build import events_for, strategy_code
from quantbot.strategies.events import EventSignalEngine, atr_series


def _trending(n=5000, seed=0):
    rng = np.random.default_rng(seed); r = 0.00025 + rng.normal(0, 0.0012, n); c = 2000 * np.exp(np.cumsum(r)); o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + abs(rng.normal(0, 0.0005, n))); l = np.minimum(o, c) * (1 - abs(rng.normal(0, 0.0005, n)))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 100.0}, index=pd.date_range("2024-01-01", periods=n, freq="15min"))


def test_ramp_and_scores_are_continuous_in_unit_interval():
    assert list(apex.ramp([0, 0.5, 1, 2], 0, 1)) == [0, 0.5, 1, 1]
    sc = apex.scores(_trending(), apex.PARAMS)
    for side in ("bull", "bear"):
        S = sc[side]["S"][~np.isnan(sc[side]["S"])]; assert S.min() >= 0 and S.max() <= 1
        if side == "bull":
            assert len(np.unique(np.round(S, 3))) > 50      # spectre continu, pas binaire (marché de test haussier ; le côté vendeur y est nul par construction)


def test_events_causal_scored_threshold_and_asymmetric_levels():
    df = _trending(); full = apex.events(df); cut = 3500; part = apex.events(df.iloc[:cut])
    k = lambda ev: [(e.ts, e.direction, round(e.stop, 6), round(e.target, 6), round(e.meta["S"], 9)) for e in ev]
    assert k([e for e in full if e.ts < df.index[cut - 1]]) == k([e for e in part if e.ts < df.index[cut - 1]])
    assert full and all(e.meta["S"] >= 0.75 and e.meta["confidence"] == min(e.meta["S"], 1.0) for e in full)
    for e in full:
        px = df.close[e.ts]; rr = abs(e.target - px) / abs(px - e.stop); assert rr > 2.5 and 7 <= e.ts.hour < 17


def test_score_is_transmitted_as_signal_confidence_and_dispatch():
    from quantbot.config import Settings
    df = _trending(); ev = events_for("apex_pullback", {"params": {}}, df); eng = EventSignalEngine(Settings(), ev)
    sig = eng.evaluate(df.loc[:ev[0].ts]); assert abs(sig.confidence - ev[0].meta["confidence"]) < 1e-12 and strategy_code("apex_pullback") == "APEX_PULLBACK_ALPHA"


def test_learning_loop_isolates_high_score_vol_expansion_losses_and_never_promotes():
    df = _trending(); ev = apex.events(df); atr = atr_series(df, 14)
    class T:  # trade perdant factice (test de la logique d'isolement uniquement)
        def __init__(s, e, bars): s.entry_time = df.index[df.index.get_loc(e.ts) + 1]; s.exit_time = df.index[df.index.get_loc(e.ts) + 1 + bars]; s.r_nominal = -1.0
    hi = [e for e in ev if e.meta["S"] > 0.85][:8]; assert len(hi) >= 5
    atr2 = atr.copy()
    for e in hi: i = df.index.get_loc(e.ts); atr2[i + 2:i + 6] = atr2[i + 1] * 2.0           # expansion de volatilité après l'entrée
    f = vol_expansion_failures([T(e, 5) for e in hi], ev, df, atr2); assert len(f) == len(hi) and all(x["S"] > 0.85 for x in f)
    h = propose_tighter_vol_filter(f, apex.PARAMS); assert h["status"] == "CANDIDATE_NOT_PROMOTED" and h["param_overrides"]["vol_hi"] < apex.PARAMS["vol_hi"]
    assert propose_tighter_vol_filter(f[:2], apex.PARAMS) is None
