import numpy as np
import pandas as pd


def monte_carlo(trades: list, initial_equity: float, n_sims: int = 1000, seed: int = 0) -> pd.DataFrame:
    """Bootstraps the sequence of realized trade PnLs (resampling with
    replacement, which also reshuffles trade order) to estimate the range of
    outcomes -- final equity and max drawdown -- the strategy's *observed*
    edge could plausibly produce, independent of the exact order trades
    happened to occur in this one backtest run."""
    if not trades:
        return pd.DataFrame()

    pnls = np.array([t.pnl_usd for t in trades])
    rng = np.random.default_rng(seed)
    n = len(pnls)

    finals, max_dds = [], []
    for _ in range(n_sims):
        sample = rng.choice(pnls, size=n, replace=True)
        equity = initial_equity + np.cumsum(sample)
        peak = np.maximum.accumulate(np.concatenate([[initial_equity], equity]))[1:]
        dd = (peak - equity) / peak
        finals.append(equity[-1])
        max_dds.append(dd.max())

    finals, max_dds = np.array(finals), np.array(max_dds)
    return pd.DataFrame({
        "metric": ["final_equity_p5", "final_equity_p50", "final_equity_p95",
                   "max_drawdown_pct_p5", "max_drawdown_pct_p50", "max_drawdown_pct_p95",
                   "prob_profitable_pct"],
        "value": [
            round(np.percentile(finals, 5), 2), round(np.percentile(finals, 50), 2),
            round(np.percentile(finals, 95), 2),
            round(np.percentile(max_dds, 5) * 100, 2), round(np.percentile(max_dds, 50) * 100, 2),
            round(np.percentile(max_dds, 95) * 100, 2),
            round((finals > initial_equity).mean() * 100, 2),
        ],
    })
