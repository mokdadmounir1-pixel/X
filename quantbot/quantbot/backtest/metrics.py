"""Métriques de performance (après coûts)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..execution.broker import Trade


def compute_metrics(trades: list[Trade], equity: pd.Series, initial: float,
                    periods_per_year: float = 24 * 365) -> dict:
    n = len(trades)
    pnls = np.array([t.pnl for t in trades], dtype=float)
    wins, losses = pnls[pnls > 0], pnls[pnls < 0]
    final = float(equity.iloc[-1]) if len(equity) else initial
    peak = equity.cummax() if len(equity) else equity
    max_dd = float(((peak - equity) / peak).max()) if len(equity) else 0.0
    rets = equity.pct_change().dropna() if len(equity) > 1 else pd.Series(dtype=float)
    sharpe = float(rets.mean() / rets.std() * np.sqrt(periods_per_year)) if len(rets) > 2 and rets.std() > 0 else 0.0
    gross_loss = float(-losses.sum())
    return {
        "n_trades": n,
        "total_return": final / initial - 1.0,
        "win_rate": float((pnls > 0).mean()) if n else 0.0,
        "profit_factor": float(wins.sum() / gross_loss) if gross_loss > 0 else (float("inf") if wins.size else 0.0),
        "expectancy": float(pnls.mean()) if n else 0.0,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "final_equity": final,
    }
