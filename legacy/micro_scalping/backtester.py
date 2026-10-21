from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import ScalpingConfig
from .strategy import add_indicators, generate_signal


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    qty: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    pnl: float | None = None
    reason: str | None = None


class Backtester:
    def __init__(self, cfg: ScalpingConfig, target_trades: int = 100):
        self.cfg = cfg
        self.target_trades = target_trades
        self.equity = cfg.initial_equity
        self.trades: list[Trade] = []
        self.equity_curve: list[float] = []

    def run(self, df: pd.DataFrame) -> list[Trade]:
        cfg = self.cfg
        df = add_indicators(df, cfg)

        position: Trade | None = None
        cooldown = 0
        current_day = None
        trades_today = 0

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]
            day = row.name.date() if hasattr(row.name, "date") else None

            if day != current_day:
                current_day = day
                trades_today = 0

            if position is not None:
                closed = self._try_close(position, row)
                if closed:
                    self.trades.append(position)
                    position = None
                    cooldown = cfg.cooldown_bars

            if cooldown > 0:
                cooldown -= 1

            if (
                position is None
                and cooldown == 0
                and len(self.trades) < self.target_trades
                and trades_today < cfg.max_trades_per_day
            ):
                signal = generate_signal(row, prev_row, cfg)
                if signal:
                    position = self._open_trade(signal, row)
                    trades_today += 1

            self.equity_curve.append(self.equity)

            if len(self.trades) >= self.target_trades:
                break

        return self.trades

    def _open_trade(self, side: str, row) -> Trade:
        cfg = self.cfg
        slip = cfg.slippage_pct / 100
        entry_price = row.close * (1 + slip if side == "long" else 1 - slip)

        stop_dist = row.atr * cfg.sl_atr_mult
        target_dist = row.atr * cfg.tp_atr_mult
        if side == "long":
            stop_price = entry_price - stop_dist
            target_price = entry_price + target_dist
        else:
            stop_price = entry_price + stop_dist
            target_price = entry_price - target_dist

        risk_amount = self.equity * cfg.risk_per_trade_pct / 100
        qty = risk_amount / stop_dist if stop_dist > 0 else 0.0

        return Trade(side, row.name, entry_price, stop_price, target_price, qty)

    def _try_close(self, trade: Trade, row) -> bool:
        if trade.side == "long":
            hit_stop = row.low <= trade.stop_price
            hit_target = row.high >= trade.target_price
        else:
            hit_stop = row.high >= trade.stop_price
            hit_target = row.low <= trade.target_price

        # If both levels fall inside the same bar's range we can't know which
        # was touched first from OHLC alone, so assume the stop hit first
        # (conservative, avoids overstating performance).
        if hit_stop:
            exit_price, reason = trade.stop_price, "stop"
        elif hit_target:
            exit_price, reason = trade.target_price, "target"
        else:
            return False

        direction = 1 if trade.side == "long" else -1
        gross_pnl = (exit_price - trade.entry_price) * trade.qty * direction
        fees = (trade.entry_price + exit_price) * trade.qty * (self.cfg.commission_pct / 100)
        net_pnl = gross_pnl - fees

        trade.exit_time = row.name
        trade.exit_price = exit_price
        trade.pnl = net_pnl
        trade.reason = reason
        self.equity += net_pnl
        return True
