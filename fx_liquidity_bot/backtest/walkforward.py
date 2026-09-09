import pandas as pd

from ..engine.scanner import PortfolioScanner
from .metrics import summarize


def walk_forward(data: dict, cfg, n_folds: int = 4) -> pd.DataFrame:
    """Chronological walk-forward split: runs the strategy on each fold in
    isolation so you can see whether performance holds up across successive
    out-of-sample periods, rather than trusting one aggregate backtest.

    This function only handles the chronological slicing + evaluation with a
    FIXED config. If you have a parameter optimizer, run it on each fold's
    prior data and pass a fold-specific cfg in yourself -- that's the natural
    extension point for true walk-forward optimization.
    """
    any_pair = next(iter(data.values()))
    n = len(any_pair)
    bounds = [int(n * i / n_folds) for i in range(n_folds + 1)]

    results = []
    for f in range(n_folds):
        start, end = bounds[f], bounds[f + 1]
        fold_data = {pair: df.iloc[start:end] for pair, df in data.items()}
        first_pair = next(iter(fold_data))
        if len(fold_data[first_pair]) < 200:
            continue

        scanner = PortfolioScanner(cfg)
        trades = scanner.run(fold_data)
        stats = summarize(trades, cfg.initial_equity)
        stats["fold"] = f + 1
        stats["start"] = fold_data[first_pair].index[0]
        stats["end"] = fold_data[first_pair].index[-1]
        results.append(stats)

    return pd.DataFrame(results)
