from __future__ import annotations

import numpy as np
import pandas as pd


def fetch_ohlcv_ccxt(
    symbol: str = "BTC/USDT",
    timeframe: str = "1m",
    limit: int = 1500,
    exchange_id: str = "binance",
) -> pd.DataFrame:
    import ccxt

    exchange = getattr(ccxt, exchange_id)()
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    df.set_index("ts", inplace=True)
    return df


def generate_synthetic_ohlcv(
    n_bars: int = 3000, start_price: float = 100.0, seed: int = 42
) -> pd.DataFrame:
    """Random-walk minute bars with mixed volatility regimes, for offline
    testing when no live market data / API is available."""
    rng = np.random.default_rng(seed)
    minutes = pd.date_range("2026-01-01", periods=n_bars, freq="1min")

    returns = rng.normal(loc=0.0, scale=0.0015, size=n_bars)
    regime = rng.choice([0.5, 1.0, 2.0], size=n_bars, p=[0.5, 0.35, 0.15])
    returns *= regime

    close = start_price * np.cumprod(1 + returns)
    open_ = np.roll(close, 1)
    open_[0] = start_price
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.0012, n_bars))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.0012, n_bars))
    volume = rng.uniform(10, 200, n_bars)

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=minutes,
    )
