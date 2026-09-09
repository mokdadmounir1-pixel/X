from dataclasses import dataclass

from ..instruments import LOT_UNITS, PIP_SIZE, pip_value_usd


@dataclass
class RiskState:
    equity: float
    peak_equity: float
    day: object = None
    day_start_equity: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    open_positions: int = 0
    daily_halt: bool = False
    permanent_halt: bool = False
    halt_reason: str = ""


class RiskManager:
    """Never increases risk to recover a loss (position sizing is always a
    fixed % of *current* equity) and enforces every hard limit as a gate on
    new entries -- it never closes or resizes an existing trade to comply."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.state = RiskState(equity=cfg.initial_equity, peak_equity=cfg.initial_equity)

    def new_day(self, day):
        s = self.state
        s.day = day
        s.day_start_equity = s.equity
        s.trades_today = 0
        s.consecutive_losses = 0
        s.daily_halt = False

    def can_enter(self):
        s, cfg = self.state, self.cfg
        if s.permanent_halt:
            return False, s.halt_reason
        if s.daily_halt:
            return False, "daily_halt_active"
        if s.trades_today >= cfg.max_trades_per_day:
            return False, "daily_trade_cap_reached"
        if s.open_positions >= cfg.max_concurrent_trades:
            return False, "concurrent_limit_reached"
        return True, ""

    def position_size_units(self, pair, entry, stop) -> float:
        risk_amount = self.state.equity * self.cfg.risk_per_trade_pct / 100
        sl_pips = abs(entry - stop) / PIP_SIZE[pair]
        if sl_pips <= 0:
            return 0.0
        pip_val_per_lot = pip_value_usd(pair, entry, LOT_UNITS)
        pip_val_per_unit = pip_val_per_lot / LOT_UNITS
        return risk_amount / (sl_pips * pip_val_per_unit)

    def register_open(self):
        self.state.open_positions += 1
        self.state.trades_today += 1

    def register_close(self, pnl: float):
        s, cfg = self.state, self.cfg
        s.open_positions -= 1
        s.equity += pnl
        s.peak_equity = max(s.peak_equity, s.equity)
        s.consecutive_losses = s.consecutive_losses + 1 if pnl <= 0 else 0

        if s.consecutive_losses >= cfg.max_consecutive_losses:
            s.daily_halt = True

        if s.day_start_equity > 0:
            daily_pnl_pct = (s.equity - s.day_start_equity) / s.day_start_equity * 100
            if daily_pnl_pct <= -cfg.max_daily_loss_pct:
                s.daily_halt = True

        drawdown_pct = (s.peak_equity - s.equity) / s.peak_equity * 100
        if drawdown_pct >= cfg.max_drawdown_pct:
            s.permanent_halt = True
            s.halt_reason = "max_drawdown_breached"
