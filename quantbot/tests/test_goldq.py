import numpy as np
import pandas as pd
import pytest

from quantbot.strategies import goldq
from quantbot.strategies.build import events_for, strategy_code


def _gold(n=6000, seed=0):
    rng = np.random.default_rng(seed); c = 2000 * np.exp(np.cumsum(rng.normal(0, 0.0012, n))); o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + abs(rng.normal(0, 0.0007, n))); l = np.minimum(o, c) * (1 - abs(rng.normal(0, 0.0007, n)))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 100.0}, index=pd.date_range("2024-01-01", periods=n, freq="15min"))


@pytest.mark.parametrize("name", list(goldq.GENERATORS))
def test_causal_prefix_equality_and_valid_levels(name):
    df = _gold(); full = goldq.events(df, name); cut = 4000
    part = goldq.events(df.iloc[:cut], name)
    key = lambda ev: [(e.ts, e.direction, round(e.stop, 6), None if e.target is None else round(e.target, 6)) for e in ev]
    assert key([e for e in full if e.ts < df.index[cut - 1]]) == key([e for e in part if e.ts < df.index[cut - 1]])
    for e in full:
        px = df.close[e.ts]
        assert (e.stop < px < e.target) if e.direction == "bullish" else (e.target < px < e.stop)
        assert 7 <= e.ts.hour < 17 or name == "gq_asia_break"


def test_asia_break_once_per_day_and_dispatch():
    df = _gold(); ev = goldq.events(df, "gq_asia_break")
    assert len({e.ts.date() for e in ev}) == len(ev)
    assert events_for("gq_zrev", {"params": {}}, df) == goldq.events(df, "gq_zrev") and strategy_code("gq_sweep") == "XAU_LIQ_SWEEP"


def test_variant_names_route_to_base_generator_with_overrides():
    df = _gold(); a = events_for("gq_sweep__rr05", {"params": {"rr": 0.5}}, df); b = events_for("gq_sweep", {"params": {"rr": 2.0}}, df)
    assert [e.ts for e in a] == [e.ts for e in b] and a and a[0].target != b[0].target
    assert strategy_code("gq_zrev__s20") == "XAU_ZREV_S20"
