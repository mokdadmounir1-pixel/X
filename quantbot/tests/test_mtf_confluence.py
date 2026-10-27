import numpy as np
import pandas as pd
import pytest

from quantbot.strategies import mtf_confluence as mc
from tests.test_apex import _trending


def _long(n=12000, seed=2):
    rng = np.random.default_rng(seed); r = rng.normal(0, 0.0012, n); r[: n // 2] += 0.0004; r[n // 2:] -= 0.0004          # hausse puis baisse : les deux sens existent
    c = 2000 * np.exp(np.cumsum(r)); o = np.r_[c[0], c[:-1]]; h = np.maximum(o, c) * 1.0004; l = np.minimum(o, c) * 0.9996
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 100.0}, index=pd.date_range("2024-01-01", periods=n, freq="15min"))


def test_htf_scores_use_only_completed_bars_no_leak():
    df = _long(); base = mc.htf_trend(df, "4h", 20, 50, 1.5)
    i = 9000; d2 = df.copy(); d2.iloc[i:i + 1, d2.columns.get_loc("close")] *= 1.05; d2.iloc[i, d2.columns.get_loc("high")] = d2.iloc[i].close * 1.01      # on altère la barre COURANTE
    alt = mc.htf_trend(d2, "4h", 20, 50, 1.5)
    assert np.allclose(base["bull"][: i + 1], alt["bull"][: i + 1], equal_nan=True) and np.allclose(base["atr_ratio"][: i + 1], alt["atr_ratio"][: i + 1], equal_nan=True)   # le score à i ne voit pas la barre HTF en cours


def test_scores_are_in_unit_interval_and_top_down_zero_kills_the_setup():
    df = _long(); om = mc.omega_series(df, mc.PARAMS)
    for side in ("bull", "bear"):
        o = om[side]["omega"][~np.isnan(om[side]["omega"])]; assert o.min() >= 0 and o.max() <= 1 + 1e-9
    p = {**mc.PARAMS}; bear_d1 = mc.htf_trend(df, "1D", 10, 30, 1.5)["bull"]
    zero = (bear_d1 == 0) & ~np.isnan(bear_d1); assert zero.any() and np.nanmax(om["bull"]["omega"][zero]) < 1e-3          # D1 non haussier -> Ω haussier ~ 0 (pas de contre-tendance)


def test_events_causal_levels_and_confluence_detail():
    df = _long(); full = mc.events(df, {"omega_min": 0.5}); cut = 9500; part = mc.events(df.iloc[:cut], {"omega_min": 0.5}); k = lambda ev: [(e.ts, e.direction, round(e.stop, 6)) for e in ev]
    assert k([e for e in full if e.ts < df.index[cut - 1]]) == k([e for e in part if e.ts < df.index[cut - 1]]) and full
    for e in full:
        px = df.close[e.ts]; assert abs(e.target - px) / abs(px - e.stop) == pytest.approx(3.0) and e.meta["omega"] >= 0.5 and {"s_S", "s_1D", "s_4h", "s_1h"} <= set(e.meta)
