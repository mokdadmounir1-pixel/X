"""Backtest barre par barre, sans look-ahead.

Le signal est calculé à la clôture de la barre t, l'ordre est exécuté à
l'ouverture de t+1. Si SL et TP sont touchés dans la même barre, le SL prime.
Les fenêtres de détection ne contiennent que des données passées.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from ..config import Settings
from ..data.loaders import resample_ohlcv
from ..data.validation import validate_ohlcv
from ..execution.broker import PaperBroker, Trade
from ..logging_utils import get_logger
from ..risk.manager import RiskManager, TradePlan
from ..signals.engine import SignalEngine
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
    def __init__(self, settings: Settings, cost_multiplier: float = 1.0) -> None:
        self.settings = settings
        self.cost_multiplier = cost_multiplier

    def run(self, df: pd.DataFrame) -> BacktestResult:
        s = self.settings
        bt = s.backtest
        df = validate_ohlcv(df, min_rows=bt.warmup_bars + 2)
        engine = SignalEngine(s)
        risk = RiskManager(s.risk)
        broker = PaperBroker(bt.initial_equity, s.execution, self.cost_multiplier)
        o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
        idx = df.index
        equity = np.full(len(df), np.nan)
        pending: Optional[TradePlan] = None
        n_signals = 0
        rejections: dict[str, int] = {}

        for t in range(bt.warmup_bars, len(df)):
            if pending is not None and broker.position is None:
                broker.open_position(pending, float(o[t]), idx[t], t)
                risk.register_open(idx[t], broker.equity())
                pending = None

            pos = broker.position
            if pos is not None:
                exit_info = self._check_exit(pos, o[t], h[t], l[t], c[t], t - pos.entry_idx, bt.max_hold_bars)
                if exit_info is not None:
                    price, reason, market = exit_info
                    trade = broker.close_position(price, idx[t], reason, t, market)
                    risk.register_close(idx[t], trade.pnl, broker.equity())

            equity[t] = broker.equity(float(c[t]))

            if broker.position is None and pending is None and t < len(df) - 1:
                ok, why = risk.can_trade(idx[t], broker.equity())
                if not ok:
                    rejections[why] = rejections.get(why, 0) + 1
                    continue
                window = df.iloc[max(0, t - bt.window_bars + 1): t + 1]
                htf = None
                if s.signals.trend_filter == "htf":
                    htf = resample_ohlcv(window, s.signals.htf_rule)
                signal = engine.evaluate(window, htf)
                if signal is None:
                    continue
                n_signals += 1
                plan = risk.build_plan(signal, broker.equity())
                if plan is None:
                    key = risk.last_rejection or "plan"
                    rejections[key] = rejections.get(key, 0) + 1
                    continue
                pending = plan

        if broker.position is not None:
            trade = broker.close_position(float(c[-1]), idx[-1], "end_of_data", len(df) - 1)
            equity[-1] = broker.equity()
        curve = pd.Series(equity, index=idx).dropna()
        metrics = compute_metrics(broker.trades, curve, bt.initial_equity)
        log.info("Backtest: %d trades, rendement %.2f%%, DD %.2f%%", metrics["n_trades"],
                 metrics["total_return"] * 100, metrics["max_drawdown"] * 100)
        return BacktestResult(broker.trades, curve, metrics, n_signals, rejections)

    @staticmethod
    def _check_exit(pos, o, h, l, c, held, max_hold):
        """Retourne (prix, raison, ordre_au_marché) ou None."""
        if pos.side == "long":
            if o <= pos.stop:
                return float(o), "stop_gap", True
            if l <= pos.stop:
                return pos.stop, "stop_loss", True
            if h >= pos.take_profit:
                return pos.take_profit, "take_profit", False
        else:
            if o >= pos.stop:
                return float(o), "stop_gap", True
            if h >= pos.stop:
                return pos.stop, "stop_loss", True
            if l <= pos.take_profit:
                return pos.take_profit, "take_profit", False
        if held >= max_hold:
            return float(c), "max_hold", True
        return None
