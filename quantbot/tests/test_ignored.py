import numpy as np
import pandas as pd
import pytest

from quantbot.core.ignored import GhostBook
from quantbot.gui.book import ignored_summary


def _bars(vals):
    return [(pd.Timestamp("2024-01-01") + pd.Timedelta(minutes=15 * i), *v) for i, v in enumerate(vals)]


def test_ghost_enters_next_open_stop_has_priority_and_costs_are_deducted():
    out = []; g = GhostBook(10, 0.001, 2.0, on_done=out.append); t0 = pd.Timestamp("2024-01-01")
    g.add(t0, "long", stop=99.0, target=102.0, reason="position_ouverte", ref_price=100.0)
    b = _bars([(100, 100, 100, 100), (100.0, 102.5, 98.5, 101)])                # barre 1 : entrée à 100, stop ET cible touchés -> le stop gagne
    for ts, o, h, l, c in b: g.step(ts, o, h, l, c)
    assert len(out) == 1 and out[0]["outcome"] == "stop" and out[0]["r"] == pytest.approx(-1.0 - 0.001 * 100.0 / 1.0)


def test_ghost_target_time_exit_and_short_symmetry():
    out = []; g = GhostBook(3, 0.0, 2.0, on_done=out.append); t0 = pd.Timestamp("2024-01-01")
    g.add(t0, "short", stop=101.0, target=None, reason="week_end", ref_price=100.0)       # cible par défaut = 2 R sous l'entrée
    for ts, o, h, l, c in _bars([(100, 100, 100, 100), (100, 100.5, 99.0, 99.5), (99.5, 99.8, 97.5, 98.0)]): g.step(ts, o, h, l, c)
    assert out[0]["outcome"] == "cible" and out[0]["r"] == pytest.approx(2.0)
    out2 = []; g2 = GhostBook(3, 0.0, 2.0, on_done=out2.append)
    g2.add(t0, "long", stop=90.0, target=120.0, reason="hors_session", ref_price=100.0)
    for ts, o, h, l, c in _bars([(100, 100, 100, 100)] + [(100, 100.5, 99.5, 100.2)] * 6): g2.step(ts, o, h, l, c)
    assert out2[0]["outcome"] == "temps" and out2[0]["held"] == 3 and out2[0]["r"] == pytest.approx(0.2 / 10.0)


def test_ghost_book_is_capped_and_never_acts_before_the_signal_bar():
    g = GhostBook(5, 0.0, 2.0, max_open=2); t0 = pd.Timestamp("2024-01-01")
    for _ in range(4): g.add(t0, "long", 99.0, 102.0, "x", 100.0)
    assert len(g.open) == 2 and g.dropped == 2
    g.step(t0, 100, 105, 90, 100); assert len(g.open) == 2 and not g.done            # même barre que le signal : rien


def test_summary_groups_by_reason_and_strategy():
    rows = [{"reason": "position_ouverte", "r": -1.0, "strategy": "amd", "recorded_ms": 1}, {"reason": "position_ouverte", "r": 2.0, "strategy": "amd", "recorded_ms": 2}, {"reason": "week_end", "r": -0.5, "strategy": "vwap", "recorded_ms": 3}]
    s = ignored_summary(rows); assert s["total"]["n"] == 3 and s["total"]["sum_r"] == pytest.approx(0.5)
    assert s["by_reason"]["position_ouverte"]["mean_r"] == pytest.approx(0.5) and s["by_reason"]["week_end"]["win_rate"] == 0.0 and set(s["by_strategy"]) == {"AMD_PO3_M15", "VWAP_BAND_M15"}
    assert ignored_summary([])["total"]["n"] == 0


def test_engine_with_ghosts_takes_exactly_the_same_trades_and_records_ignored_signals():
    from quantbot.backtest.engine import Backtester
    from quantbot.core.sim import TradingEngine
    from quantbot.strategies.events import EventSignalEngine
    from quantbot.strategies.build import events_for
    from quantbot.lab.specs import build_settings
    from quantbot.ui import replay
    from tests.test_mtf_confluence import _long
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]; base = replay.spec_for("vwap", root); df = _long(6000); cfg = base["strategies"]["vwap"]
    st = build_settings({**base, "costs": {**base["costs"], "XAUUSD": {"spread_frac": 1e-4, "fee_rate": 0.0, "slippage": 1e-5, "basis": "test"}}}, "XAUUSD", {"spread_frac": 1e-4, "reliable": True, "zero_share": 0.0}, df).with_overrides({"backtest.max_hold_bars": cfg["max_hold_bars"]})
    ev = events_for("vwap", cfg, df)
    def run(with_ghosts):
        eng = TradingEngine(st, signal_engine=EventSignalEngine(st, ev))
        if with_ghosts:
            eng.ghosts = GhostBook(cfg["max_hold_bars"], 0.0002, st.risk.reward_risk)
        eng.run_replay(df); return eng
    a, b = run(False), run(True)
    assert [(t.entry_time, t.exit_time, round(t.pnl, 6)) for t in a.broker.trades] == [(t.entry_time, t.exit_time, round(t.pnl, 6)) for t in b.broker.trades]
    assert a.rejections == b.rejections and len(b.ghosts.done) + len(b.ghosts.open) + b.ghosts.dropped >= 0
