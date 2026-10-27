import numpy as np
import pandas as pd
import pytest

from quantbot.strategies import cta_donchian as cta
from quantbot.strategies.build import events_for, strategy_code
from tests.test_mtf_confluence import _long


def test_signals_follow_completed_h4_breakouts_with_d1_alignment_and_valid_levels():
    df = _long(20000); ev = cta.events(df, {"channel": 10, "d1_min": 0.1}); assert ev
    for e in ev:
        px = df.close[e.ts]; assert (e.stop < px < e.target) if e.direction == "bullish" else (e.target < px < e.stop)
        assert 7 <= e.ts.hour < 21 and abs(e.target - px) / abs(px - e.stop) == pytest.approx(2.0, rel=0.05) and e.meta["d1"] >= 0.1
    assert {e.direction for e in ev} == {"bullish", "bearish"}                           # marché haussier puis baissier : les deux sens


def test_causal_prefix_and_dispatch():
    df = _long(20000); cut = 14000; full = cta.events(df, {"channel": 10, "d1_min": 0.1}); part = cta.events(df.iloc[:cut], {"channel": 10, "d1_min": 0.1})
    k = lambda ev: [(e.ts, e.direction, round(e.stop, 6)) for e in ev]
    assert k([e for e in full if e.ts < df.index[cut - 10]]) == k([e for e in part if e.ts < df.index[cut - 10]])
    assert events_for("cta_donchian", {"params": {"channel": 10}}, df) == cta.events(df, {"channel": 10}) and strategy_code("cta_donchian") == "CTA_DONCHIAN_H4"
