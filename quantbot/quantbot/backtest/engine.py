"""Backtest = rejeu barre par barre du moteur unique `core.sim.TradingEngine` (sans look-ahead).

Le signal est calculé à la clôture de la barre t, l'ordre est exécuté à l'ouverture de t+1.
Si SL et TP sont touchés dans la même barre, le SL prime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from ..config import Settings
from ..core.sim import TradingEngine, check_exit
from ..data.validation import validate_ohlcv
from ..execution.broker import PaperBroker, Trade
from ..logging_utils import get_logger
from .metrics import compute_metrics

log = get_logger("backtest")


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series
    metrics: dict
    n_signals: int = 0
    rejections: dict = field(default_factory=dict)


class Backtester:
    _check_exit = staticmethod(check_exit)

    def __init__(self, settings: Settings, cost_multiplier: float = 1.0, signal_engine: Any = None) -> None:
        self.settings = settings
        self.cost_multiplier = cost_multiplier
        self.signal_engine = signal_engine

    def run(self, df: pd.DataFrame) -> BacktestResult:
        s = self.settings
        df = validate_ohlcv(df, min_rows=s.backtest.warmup_bars + 2)
        broker = PaperBroker(s.backtest.initial_equity, s.execution, self.cost_multiplier)
        engine = TradingEngine(s, broker=broker, signal_engine=self.signal_engine)
        engine.run_replay(df)
        engine.finish(df)
        curve = pd.Series(engine.equity_v, index=engine.equity_ts)
        metrics = compute_metrics(broker.trades, curve, s.backtest.initial_equity)
        log.info("Backtest: %d trades, rendement %.2f%%, DD %.2f%%", metrics["n_trades"],
                 metrics["total_return"] * 100, metrics["max_drawdown"] * 100)
        return BacktestResult(broker.trades, curve, metrics, engine.n_signals, engine.rejections)
