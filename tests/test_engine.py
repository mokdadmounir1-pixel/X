import numpy as np
import pandas as pd

from quantlab.engine import Costs, EngineCfg, Signals, run
from quantlab.research import null_test
from quantlab.synth import block_bootstrap, make_ohlcv


def _flat(n=50, px=100.0):
    idx = pd.date_range("2026-01-01", periods=n, freq="1min")
    return pd.DataFrame(dict(open=px, high=px, low=px, close=px, volume=1.0), index=idx)


def _sig(df, i, side, sl=1.0, tp=2.0):
    s = np.zeros(len(df), int); s[i] = side
    return Signals(s, np.full(len(df), sl), np.full(len(df), tp), 20)


def test_no_lookahead_entry_is_next_open():
    df = _flat()
    df.iloc[6, df.columns.get_loc("open")] = 101.0
    tr, _ = run(df, _sig(df, 5, 1), EngineCfg(costs=Costs(0, 0, 0)))
    assert tr.entry.iloc[0] == 101.0 and tr.entry_i.iloc[0] == 6


def test_target_hit_pays_r_multiple_without_costs():
    df = _flat(); df.iloc[8, df.columns.get_loc("high")] = 102.5
    tr, eq = run(df, _sig(df, 5, 1), EngineCfg(costs=Costs(0, 0, 0)))
    assert tr.reason.iloc[0] == "target" and abs(tr.r.iloc[0] - 2.0) < 1e-6


def test_stop_wins_when_both_inside_one_bar():
    df = _flat(); df.iloc[8, df.columns.get_loc("high")] = 105; df.iloc[8, df.columns.get_loc("low")] = 95
    tr, _ = run(df, _sig(df, 5, 1), EngineCfg(costs=Costs(0, 0, 0)))
    assert tr.reason.iloc[0] == "stop" and tr.r.iloc[0] < 0


def test_costs_reduce_pnl():
    df = _flat(); df.iloc[8, df.columns.get_loc("high")] = 102.5
    a, _ = run(df, _sig(df, 5, 1), EngineCfg(costs=Costs(0, 0, 0)))
    b, _ = run(df, _sig(df, 5, 1), EngineCfg())
    assert b.pnl.iloc[0] < a.pnl.iloc[0]


def test_synth_and_bootstrap_shapes():
    df = make_ohlcv(3000)
    nb = block_bootstrap(df)
    assert len(nb) == len(df) and (nb.high >= nb[["open", "close"]].max(axis=1) - 1e-9).all()


def test_null_test_runs():
    df = make_ohlcv(4000)
    r = null_test("bb_reversion", {}, df, EngineCfg(), n=3)
    assert 0 < r["p_value"] <= 1
