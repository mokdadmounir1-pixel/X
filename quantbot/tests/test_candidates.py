import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbot.strategies import gap_fade, ibs_reversion, london_breakout, orb_stocks_in_play, rsi2_reversion, turn_of_month
from quantbot.strategies.build import STRATEGY_CODES, events_for, strategy_code
from quantbot.strategies.sessions import cash_sessions, mean_range
from tests.test_mtf_confluence import _long

ROOT = Path(__file__).resolve().parents[1]


def _cash(days=60, seed=1, gaps=None, vols=None, start="2024-03-04"):
    """Barres M15 des seules séances cash NY (lundi-vendredi) ; `gaps[d]` = écart d'ouverture du jour d ; `vols[d]` = volume de la barre 09:30."""
    rng = np.random.default_rng(seed); rows = []; px = 100.0; ds = pd.bdate_range(start, periods=days)
    for d, day in enumerate(ds):
        px += (gaps or {}).get(d, rng.normal(0, 0.15))
        for k in range(26):
            t = (day + pd.Timedelta(hours=9, minutes=30 + 15 * k)).tz_localize("America/New_York").tz_convert("UTC").tz_localize(None)
            o = px; c = px + rng.normal(0, 0.25); rows.append((t, o, max(o, c) + 0.1, min(o, c) - 0.1, c, (vols or {}).get(d, 100.0) if k == 0 else 100.0)); px = c
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"]).set_index("time")


def test_sessions_are_complete_and_range_uses_only_finished_sessions():
    df = _cash(30); ss = cash_sessions(df); assert len(ss) == 30 and all(s["complete"] for s in ss)
    assert np.isnan(mean_range(ss, 2)) and mean_range(ss, 20) > 0
    part = cash_sessions(df.iloc[:-5]); assert part[-1]["complete"] is False


def test_gap_fade_fades_moderate_gaps_toward_prior_close_and_ignores_huge_or_tiny_gaps():
    A = np.mean([s["high"] - s["low"] for s in cash_sessions(_cash(40))[:12]])
    df = _cash(40, gaps={20: 0.6 * A * 1.0, 25: -0.7 * A, 30: 12 * A, 32: 0.02}); ev = gap_fade.events(df)
    days = {pd.Timestamp(e.ts).tz_localize("UTC").tz_convert("America/New_York").normalize().tz_localize(None) for e in ev}; ds = pd.bdate_range("2024-03-04", periods=40)
    assert ds[20] in days and ds[30] not in days and ds[32] not in days            # écart modéré combattu ; énorme (nouvelle) et minuscule ignorés
    for e in ev:
        px = df.close[e.ts]; assert (e.stop > px > e.target) if e.direction == "bearish" else (e.stop < px < e.target)
        assert 0.55 <= e.meta["confidence"] <= 0.95


def test_ibs_buys_after_closes_at_the_low_and_sells_after_closes_at_the_high_mirror_symmetric():
    df = _cash(60, seed=3); ev = ibs_reversion.events(df); assert ev and {e.direction for e in ev} == {"bullish", "bearish"}
    for e in ev:
        px = df.close[e.ts]; assert (e.stop < px < e.target) if e.direction == "bullish" else (e.target < px < e.stop)
        assert (e.meta["ibs"] <= 0.2) == (e.direction == "bullish")
    mirror = df.copy(); mirror["open"], mirror["close"], mirror["high"], mirror["low"] = 400 - df.open, 400 - df.close, 400 - df.low, 400 - df.high
    me = ibs_reversion.events(mirror); assert len(me) == len(ev) and {e.ts for e in me} == {e.ts for e in ev}


def test_rsi2_needs_oversold_with_uptrend_and_is_valid():
    df = _cash(120, seed=5); ev = rsi2_reversion.events(df, {"rsi_low": 30.0, "rsi_high": 70.0}); assert ev
    for e in ev:
        px = df.close[e.ts]; assert (e.stop < px < e.target) if e.direction == "bullish" else (e.target < px < e.stop)
    r = rsi2_reversion.rsi2(np.array([1, 2, 3, 4, 5.0, 6])); assert r[-1] == 100.0 and np.isnan(r[1])
    assert rsi2_reversion.rsi2(np.array([6, 5, 4, 3, 2.0, 1]))[-1] == pytest.approx(0.0)


def test_turn_of_month_signals_on_last_weekday_of_each_month_only_long():
    df = _cash(130, seed=2); ev = turn_of_month.events(df); assert 4 <= len(ev) <= 7 and all(e.direction == "bullish" for e in ev)
    for e in ev:
        d = pd.Timestamp(e.ts).tz_localize("UTC").tz_convert("America/New_York").normalize(); assert turn_of_month.next_weekday(d).month != d.month and df.close[e.ts] > e.stop


def test_london_breakout_continues_in_the_break_direction_with_opposite_edge_stop():
    df = _long(12000); ev = london_breakout.events(df); assert ev and {e.direction for e in ev} == {"bullish", "bearish"}
    for e in ev:
        px = df.close[e.ts]; assert 7 <= e.ts.hour < 10 and ((e.stop < px < e.target) if e.direction == "bullish" else (e.target < px < e.stop))
    assert len({e.ts.normalize() for e in ev}) == len(ev)                                # une tentative par jour


def test_orb_stocks_in_play_needs_unusual_opening_volume_and_clean_data():
    quiet = _cash(40, seed=7); assert orb_stocks_in_play.events(quiet) == []
    A = np.mean([s["high"] - s["low"] for s in cash_sessions(quiet)[:12]]); assert A > 0.5
    loud = _cash(40, seed=7, vols={30: 900.0}); ev = orb_stocks_in_play.events(loud, {"min_atr": 0.1}); assert len(ev) == 1
    for e in ev:
        assert e.meta["rvol"] >= 2.0 and abs(loud.close[e.ts] - e.stop) == pytest.approx(0.10 * np.mean([s["high"] - s["low"] for s in cash_sessions(loud)[16:30]]), rel=0.5)
    assert orb_stocks_in_play.events(_cash(10, vols={9: 900.0})) == []                    # < 14 séances d'historique : rien


@pytest.mark.parametrize("mod,mk", [(gap_fade, lambda: _cash(80, seed=4)), (ibs_reversion, lambda: _cash(80, seed=3)), (rsi2_reversion, lambda: _cash(120, seed=5)), (turn_of_month, lambda: _cash(130, seed=2)), (london_breakout, lambda: _long(12000)), (orb_stocks_in_play, lambda: _cash(80, seed=7, vols={50: 900.0, 62: 700.0}))])
def test_causal_prefix_and_dispatch(mod, mk):
    df = mk(); name = mod.__name__.rsplit(".", 1)[1]; full = events_for(name, {"params": {"rsi_low": 30.0, "rsi_high": 70.0, "min_atr": 0.1} if name in ("rsi2_reversion", "orb_stocks_in_play") else {}}, df)
    cut = int(len(df) * 0.7); part = events_for(name, {"params": {"rsi_low": 30.0, "rsi_high": 70.0, "min_atr": 0.1} if name in ("rsi2_reversion", "orb_stocks_in_play") else {}}, df.iloc[:cut]); lim = df.index[cut - 120]
    k = lambda ev: [(e.ts, e.direction, round(e.stop, 5)) for e in ev if e.ts < lim]
    assert k(full) == k(part) and strategy_code(name) == STRATEGY_CODES[name]


def test_specs_are_paper_only_with_zero_trials_and_budget_500():
    for n in ("candidates_v1", "london_breakout_v1", "stocks_orb_v1"):
        s = json.loads((ROOT / "specs" / f"{n}.json").read_text(encoding="utf-8")); assert s["trials"] == 0 and s["max_trials_budget"] == 500 and s["strategies"]
