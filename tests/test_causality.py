import numpy as np
import pandas as pd
import pytest
from ftmo_algo.data.synth import make_series
from ftmo_algo.data.quality import resample_ohlc, align_htf
from ftmo_algo.algos.context import Ctx
from ftmo_algo.algos.library import ALGOS, BASE_ALGOS, EXIT_VARIANTS
from ftmo_algo.engine.news import NewsCalendar

M5 = make_series("US500", years=0.5, seed=3)
M15 = resample_ohlc(M5, "M15").drop(columns=["close_time"])
NEWS = NewsCalendar.default(M5.index[0], M5.index[-1] + pd.Timedelta(days=60))


@pytest.mark.parametrize("name", BASE_ALGOS)
def test_signals_on_prefix_identical_to_full_series(name):
    full = Ctx("US500", M15, news=NEWS)
    k = int(len(M15) * 0.7)
    pre = Ctx("US500", M15.iloc[:k], news=NEWS)
    a = ALGOS[name]
    s_full = a.generate(full, a.default, EXIT_VARIANTS["fixed3"])
    s_pre = a.generate(pre, a.default, EXIT_VARIANTS["fixed3"])
    assert np.array_equal(s_full.side[:k], s_pre.side)
    m = s_pre.side != 0
    assert np.allclose(s_full.stop[:k][m], s_pre.stop[m], equal_nan=True)
    assert np.array_equal(s_full.grade[:k][m], s_pre.grade[m])
    # le test n'est utile que s'il y a des signaux dans le préfixe (sinon on le signale)
    if name in ("session_orb", "squeeze_breakout", "sweep_reversal", "meanrev_z"):
        assert m.sum() > 0


def test_future_data_cannot_change_past_context():
    full = Ctx("US500", M15, news=NEWS)
    k = int(len(M15) * 0.6)
    poisoned = M15.copy()
    poisoned.iloc[k:, :4] = poisoned.iloc[k:, :4].to_numpy() * 3.7      # futur délirant
    poisoned["high"] = poisoned[["open", "high", "close"]].max(axis=1)
    poisoned["low"] = poisoned[["open", "low", "close"]].min(axis=1)
    p = Ctx("US500", poisoned, news=NEWS)
    for attr in ("h1_trend", "h4_trend", "d1_trend", "pd_high", "pd_low", "wk_high", "h1_adx", "h1_ema50", "vol_ratio",
                 "bb_z", "asia_high", "atr"):
        assert np.allclose(getattr(full, attr)[:k], getattr(p, attr)[:k], equal_nan=True), attr


def test_no_multitimeframe_leak_bar_usable_only_when_closed():
    ctx = Ctx("US500", M15, news=NEWS)
    tc = ctx.mk.tc
    for htf, ix in ((ctx.h1, ctx.ix1), (ctx.h4, ctx.ix4), (ctx.d1, ctx.ixd)):
        ct = htf["close_time"].to_numpy("datetime64[ns]").astype("int64")
        ok = ix >= 0
        assert (ct[ix[ok]] <= tc[ok]).all()                          # la barre HTF utilisée est close
        nxt = np.minimum(ix[ok] + 1, len(ct) - 1)
        has_next = ix[ok] + 1 < len(ct)
        assert (ct[nxt][has_next] > tc[ok][has_next]).all()           # et c'est la plus récente close
