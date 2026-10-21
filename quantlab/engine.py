"""Bar-level backtest engine.

Rules (deliberately pessimistic):
- A signal computed on the close of bar i is filled at the OPEN of bar i+1 (no look-ahead).
- Entry pays slippage + half the spread; exits at stop pay slippage; targets fill at the level.
- If stop and target are both inside one bar, the stop wins.
- Fees on both sides; position sized to risk `risk_pct` of equity at the stop, capped by leverage.
- Daily trade cap, cooldown, and a daily loss halt.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd


@dataclass
class Costs:
    fee_pct: float = 0.04       # per side
    slip_pct: float = 0.01      # per fill
    spread_pct: float = 0.01    # full spread, half paid on entry and on market exits


@dataclass
class EngineCfg:
    equity: float = 10_000.0
    risk_pct: float = 0.5
    max_leverage: float = 5.0
    max_trades_day: int = 40
    cooldown: int = 2
    daily_loss_halt_pct: float = 3.0
    costs: Costs = field(default_factory=Costs)

    def scaled_costs(self, k):
        c = self.costs
        return replace(self, costs=Costs(c.fee_pct * k, c.slip_pct * k, c.spread_pct * k))


@dataclass
class Signals:
    side: np.ndarray        # +1 / -1 / 0 per bar (decided at close of bar)
    sl: np.ndarray          # stop distance in price units
    tp: np.ndarray          # target distance in price units
    max_hold: int = 30      # time stop (bars)


def run(df: pd.DataFrame, sig: Signals, cfg: EngineCfg | None = None):
    cfg = cfg or EngineCfg()
    c = cfg.costs
    o, h, l, cl = (df[k].values for k in ("open", "high", "low", "close"))
    n = len(df)
    day = (df.index.values.astype("datetime64[D]").astype(np.int64)) if isinstance(df.index, pd.DatetimeIndex) else np.zeros(n, int)
    equity = cfg.equity
    eq_curve = np.full(n, equity)
    trades = []
    pos = 0
    cool = 0
    cur_day = -1
    n_day = 0
    day_start_eq = equity
    halted = False
    side = sig.side
    for i in range(1, n):
        if day[i] != cur_day:
            cur_day, n_day, day_start_eq, halted = day[i], 0, equity, False
        if pos:
            ex, reason = None, None
            if pos > 0:
                hs, ht = l[i] <= stop, h[i] >= tgt
            else:
                hs, ht = h[i] >= stop, l[i] <= tgt
            if hs:
                ex = stop * (1 - pos * c.slip_pct / 100); reason = "stop"
            elif ht:
                ex = tgt; reason = "target"
            elif i - ent_i >= hold:
                ex = cl[i] * (1 - pos * (c.slip_pct + c.spread_pct / 2) / 100); reason = "time"
            if ex is not None:
                gross = (ex - ent_px) * pos * qty
                fees = (ent_px + ex) * qty * c.fee_pct / 100
                pnl = gross - fees
                equity += pnl
                trades.append(dict(entry_i=ent_i, exit_i=i, entry_time=df.index[ent_i], exit_time=df.index[i], side=pos,
                                   entry=ent_px, exit=ex, qty=qty, pnl=pnl, r=pnl / risk_amt, reason=reason, fees=fees))
                pos = 0
                cool = cfg.cooldown
                if equity < day_start_eq * (1 - cfg.daily_loss_halt_pct / 100):
                    halted = True
        if cool > 0:
            cool -= 1
        # decide at close of bar i-1 -> fill at open of bar i (only if flat before this bar's exit logic)
        if pos == 0 and cool == 0 and not halted and n_day < cfg.max_trades_day and i >= 2:
            s = side[i - 1]
            if s != 0 and sig.sl[i - 1] > 0 and np.isfinite(sig.sl[i - 1]):
                px = o[i] * (1 + s * (c.slip_pct + c.spread_pct / 2) / 100)
                sld, tpd = sig.sl[i - 1], sig.tp[i - 1]
                risk_amt = equity * cfg.risk_pct / 100
                qty = min(risk_amt / sld, equity * cfg.max_leverage / px)
                risk_amt = qty * sld  # actual risk after leverage cap
                if qty > 0:
                    pos, ent_px, ent_i = s, px, i
                    stop, tgt, hold = px - s * sld, px + s * tpd, sig.max_hold
                    n_day += 1
                    # same-bar stop check after entry at open
                    if (s > 0 and l[i] <= stop) or (s < 0 and h[i] >= stop):
                        ex = stop * (1 - s * c.slip_pct / 100)
                        pnl = (ex - px) * s * qty - (px + ex) * qty * c.fee_pct / 100
                        equity += pnl
                        trades.append(dict(entry_i=i, exit_i=i, entry_time=df.index[i], exit_time=df.index[i], side=s, entry=px,
                                           exit=ex, qty=qty, pnl=pnl, r=pnl / risk_amt, reason="stop", fees=0.0))
                        pos = 0; cool = cfg.cooldown
        # mark to market
        eq_curve[i] = equity + ((cl[i] - ent_px) * pos * qty if pos else 0.0)
    tdf = pd.DataFrame(trades)
    return tdf, pd.Series(eq_curve, index=df.index)
