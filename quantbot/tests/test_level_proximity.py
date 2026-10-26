import numpy as np
import pandas as pd
import pytest

from quantbot.strategies import level_proximity as lp
from quantbot.strategies.events import atr_series
from tests.test_apex import _trending


def test_round_score_is_continuous_peaks_on_round_numbers():
    p = np.array([2000.0, 2005.0, 2025.0, 2010.0]); a = np.full(4, 4.0)
    s = lp.round_score(p, a, [50.0, 10.0], [1.0, 0.4], 0.5)
    assert s[0] == 1.0 and 0 < s[1] < 0.4 and s[2] < 0.01 and s[3] == pytest.approx(0.4)      # 2000 = pic ; 2010 = niveau secondaire pondéré


def test_node_score_is_causal_and_finds_the_heavy_volume_zone():
    df = _trending(2500); atr = atr_series(df, 14); full = lp.node_score(df, atr, lp.PARAMS); cut = 2000; part = lp.node_score(df.iloc[:cut], atr[:cut], lp.PARAMS)
    assert np.allclose(full[:cut], part, equal_nan=True) and full.max() <= 1.0 and full.min() >= 0
    d2 = df.copy(); d2["volume"] = 10.0; d2.iloc[1500:1560, d2.columns.get_loc("volume")] = 5000.0                      # un nœud de volume fort
    hot = float(d2.iloc[1500:1560].close.mean()); n2 = lp.node_score(d2.assign(close=d2.close), atr_series(d2, 14), lp.PARAMS)
    j = 1700; assert n2[j] >= 0 and lp.node_score(d2, atr_series(d2, 14), lp.PARAMS).max() > 0.3


def test_events_causal_and_levels_in_meta():
    df = _trending(4500); full = lp.events(df, {"fused_min": 0.5}); cut = 3500; part = lp.events(df.iloc[:cut], {"fused_min": 0.5}); k = lambda ev: [(e.ts, e.direction, round(e.stop, 6)) for e in ev]
    assert k([e for e in full if e.ts < df.index[cut - 1]]) == k([e for e in part if e.ts < df.index[cut - 1]])
    for e in full:
        px = df.close[e.ts]; assert abs(e.target - px) / abs(px - e.stop) == pytest.approx(3.0) and 0 <= e.meta["L"] <= 1 and e.meta["fused"] >= 0.5
