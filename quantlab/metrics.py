from __future__ import annotations

import numpy as np
import pandas as pd


def summarize(trades: pd.DataFrame, eq: pd.Series, equity0: float) -> dict:
    n = len(trades)
    out = dict(trades=n, net=float(eq.iloc[-1] - equity0), ret_pct=float((eq.iloc[-1] / equity0 - 1) * 100))
    dd = (eq / eq.cummax() - 1).min() * 100
    out["max_dd_pct"] = float(dd)
    if n == 0:
        return {**out, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_r": 0.0, "sharpe": 0.0, "avg_fees": 0.0, "top3_share": 0.0}
    w = trades.pnl[trades.pnl > 0].sum()
    lo = -trades.pnl[trades.pnl < 0].sum()
    daily = eq.resample("1D").last().pct_change().dropna() if isinstance(eq.index, pd.DatetimeIndex) else pd.Series(dtype=float)
    sharpe = float(daily.mean() / daily.std() * np.sqrt(365)) if len(daily) > 3 and daily.std() > 0 else 0.0
    top3 = trades.pnl.nlargest(3).sum()
    out.update(win_rate=float((trades.pnl > 0).mean() * 100), profit_factor=float(w / lo) if lo > 0 else float("inf"),
               expectancy_r=float(trades.r.mean()), sharpe=sharpe, avg_fees=float(trades.fees.mean()),
               top3_share=float(top3 / trades.pnl.sum()) if trades.pnl.sum() > 0 else 0.0)
    return out


def monte_carlo(pnl: np.ndarray, equity0: float, n_sims=2000, seed=0):
    """Reshuffle (bootstrap) trade results: distribution of final equity and max drawdown."""
    if len(pnl) < 10:
        return dict(p5_final=equity0, p50_final=equity0, p95_dd=0.0, p_loss=1.0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(pnl), (n_sims, len(pnl)))
    paths = equity0 + np.cumsum(pnl[idx], axis=1)
    peak = np.maximum.accumulate(paths, axis=1)
    dd = ((paths / peak) - 1).min(axis=1) * 100
    fin = paths[:, -1]
    return dict(p5_final=float(np.percentile(fin, 5)), p50_final=float(np.percentile(fin, 50)),
                p95_dd=float(np.percentile(dd, 5)), p_loss=float((fin < equity0).mean()))
