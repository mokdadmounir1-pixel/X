import numpy as np
import pandas as pd


def summarize(trades: list, initial_equity: float) -> dict:
    if not trades:
        return {"trades": 0}

    pnls = [t.pnl_usd for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    equity = initial_equity
    peak = equity
    max_dd = 0.0
    daily_returns: dict = {}
    for t, p in zip(trades, pnls):
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        day = t.exit_time.date()
        daily_returns[day] = daily_returns.get(day, 0.0) + p

    ret_series = pd.Series(list(daily_returns.values())) / initial_equity
    sharpe = (ret_series.mean() / ret_series.std() * np.sqrt(252)) if ret_series.std() > 0 else 0.0

    max_streak = streak = 0
    for p in pnls:
        if p <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    n = len(trades)

    return {
        "trades": n,
        "win_rate_pct": round(100 * len(wins) / n, 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
        "expectancy": round(sum(pnls) / n, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "net_pnl": round(sum(pnls), 2),
        "return_pct": round(sum(pnls) / initial_equity * 100, 2),
        "final_equity": round(equity, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe_daily_ann": round(sharpe, 2),
        "max_consecutive_losses": max_streak,
    }
