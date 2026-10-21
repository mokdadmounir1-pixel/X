from __future__ import annotations

from .backtester import Trade


def summarize(trades: list[Trade], initial_equity: float) -> dict:
    if not trades:
        return {"trades": 0}

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    equity = initial_equity
    peak = equity
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)

    gross_profit = sum(wins)
    gross_loss = -sum(losses)

    return {
        "trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2),
        "avg_win": round(sum(wins) / len(wins), 4) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "net_pnl": round(sum(pnls), 2),
        "final_equity": round(equity, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
    }
