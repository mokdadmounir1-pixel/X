import numpy as np
import pandas as pd
import pytest

from quantbot.strategies import stop_hunt_engine as sh
from quantbot.strategies.build import events_for, strategy_code


def _walk(seed=1, n=6000):
    rng = np.random.default_rng(seed); c = 2000 + np.cumsum(rng.normal(0, 1.0, n)); o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + abs(rng.normal(0, .4, n)); l = np.minimum(o, c) - abs(rng.normal(0, .4, n))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 100.0}, index=pd.date_range("2024-01-01", periods=n, freq="15min"))


def _mirror(df, M=4000.0):
    return pd.DataFrame({"open": M - df.open, "high": M - df.low, "low": M - df.high, "close": M - df.close, "volume": df.volume}, index=df.index)


def test_engine_is_mirror_symmetric_buys_and_sells_have_no_built_in_bias():
    flip = {"bullish": "bearish", "bearish": "bullish"}
    for seed in (1, 2, 3):
        df = _walk(seed); a = {e.ts: flip[e.direction] for e in sh.events(df)}; b = {e.ts: e.direction for e in sh.events(_mirror(df))}
        common = set(a) & set(b); assert len(common) >= 0.97 * max(len(a), len(b)) and all(a[t] == b[t] for t in common)     # le miroir d'un marché donne les signaux inverses aux mêmes barres
        nb, ns = sum(v == "bearish" for v in a.values()), sum(v == "bullish" for v in a.values()); assert abs(nb - ns) <= 0.35 * (nb + ns)


def test_tie_break_picks_the_most_extreme_cluster_on_both_sides():
    p = sh.PARAMS; levels = np.array([2000.0, 2000.1, 2010.0, 2010.1])                       # deux amas de même taille
    assert sh.pool_score(levels, 1.0, p, "low")[1] < 2001 and sh.pool_score(levels, 1.0, p, "high")[1] > 2009


def test_variants_are_distinct_sell_only_has_no_buys_and_flip_turns_buys_into_labelled_sells():
    df = _walk(2); both = events_for("stop_hunt", {"params": {"mode": "both"}}, df); sell = events_for("stop_hunt__sell", {"params": {"mode": "sell_only"}}, df); flip = events_for("stop_hunt__flip", {"params": {"mode": "flip"}}, df)
    assert any(e.direction == "bullish" for e in both) and all(e.direction == "bearish" for e in sell) and all(e.direction == "bearish" for e in flip)
    assert {e.meta["origin"] for e in sell} == {"sell"} and "buy_flipped" in {e.meta["origin"] for e in flip} and "sell" in {e.meta["origin"] for e in flip}
    for e in flip:
        px = df.close[e.ts]; assert e.stop > px > e.target and abs(px - e.target) / abs(e.stop - px) == pytest.approx(3.0)
    assert strategy_code("stop_hunt__sell") == "XAU_STOP_HUNT_SELL" and strategy_code("stop_hunt__flip") == "XAU_STOP_HUNT_FLIP" and strategy_code("stop_hunt") == "XAU_STOP_HUNT"


def test_buy_only_variant_has_no_sells_and_equals_the_buys_of_the_base_when_no_cooldown_interference():
    df = _walk(3); buy = events_for("stop_hunt__buy", {"params": {"mode": "buy_only"}}, df)
    assert buy and all(e.direction == "bullish" and e.meta["origin"] == "buy" for e in buy) and strategy_code("stop_hunt__buy") == "XAU_STOP_HUNT_BUY"
    import json, pathlib
    spec = json.loads((pathlib.Path(__file__).resolve().parents[1] / "specs" / "stop_hunt_v3.json").read_text(encoding="utf-8")); assert spec["trials"] == 0 and "PAPER" in spec["preregistered"]
