"""Synthetic 1-minute market with vol clustering, trend/range regimes, jumps and
intraday volume seasonality. Used to validate the engine and test robustness; it
proves nothing about real-market edge (see research.null_test for that)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def make_ohlcv(n=20000, start_price=60000.0, seed=1, freq="1min", start="2026-01-01"):
    rng = np.random.default_rng(seed)
    # Markov regimes: 0 range (mean-reverting), 1 trend up, 2 trend down
    P = np.array([[0.995, 0.0025, 0.0025], [0.004, 0.996, 0.0], [0.004, 0.0, 0.996]])
    reg = np.zeros(n, int)
    for i in range(1, n):
        reg[i] = rng.choice(3, p=P[reg[i - 1]])
    # GARCH(1,1)-style vol
    vol = np.empty(n)
    v = 0.0006
    eps_prev = 0.0
    for i in range(n):
        v = np.sqrt(1.5e-8 + 0.08 * eps_prev**2 + 0.9 * v**2)
        e = rng.standard_normal() * v
        vol[i] = v
        eps_prev = e
    z = rng.standard_normal(n)
    drift = np.where(reg == 1, 0.04, np.where(reg == 2, -0.04, 0.0)) * vol
    ret = drift + vol * z
    # mean reversion inside range regime
    price_dev = np.zeros(n)
    for i in range(1, n):
        if reg[i] == 0:
            ret[i] -= 0.08 * price_dev[i - 1]
        price_dev[i] = 0.97 * price_dev[i - 1] + ret[i] if reg[i] == 0 else 0.0
    jumps = rng.random(n) < 0.0008
    ret[jumps] += rng.normal(0, 0.004, jumps.sum())
    close = start_price * np.exp(np.cumsum(ret))
    open_ = np.r_[start_price, close[:-1]]
    rng_hi = np.abs(rng.standard_normal(n)) * vol * 0.6
    rng_lo = np.abs(rng.standard_normal(n)) * vol * 0.6
    high = np.maximum(open_, close) * (1 + rng_hi)
    low = np.minimum(open_, close) * (1 - rng_lo)
    idx = pd.date_range(start, periods=n, freq=freq)
    hour = idx.hour.values + idx.minute.values / 60
    season = 1 + 0.6 * np.exp(-((hour - 14.5) ** 2) / 8)
    volume = rng.gamma(3, 20, n) * season * (vol / vol.mean()) ** 1.0
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
    return df


def block_bootstrap(df: pd.DataFrame, block=60, seed=0) -> pd.DataFrame:
    """Null market: resample blocks of log-returns / range shape. Keeps vol clustering
    inside blocks but destroys longer-range predictable structure."""
    rng = np.random.default_rng(seed)
    n = len(df)
    c = df["close"].values
    o = df["open"].values
    lr = np.log(c / o)
    hi = np.log(df["high"].values / np.maximum(o, c))
    lo = np.log(np.minimum(o, c) / df["low"].values)
    vol = df["volume"].values
    nb = n // block + 1
    starts = rng.integers(0, n - block, nb)
    pick = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
    # random sign flip per block removes drift/trend bias
    flips = np.repeat(rng.choice([-1, 1], nb), block)[:n]
    lr2 = lr[pick] * flips
    close = c[0] * np.exp(np.cumsum(lr2))
    open_ = np.r_[c[0], close[:-1]]
    high = np.maximum(open_, close) * np.exp(hi[pick])
    low = np.minimum(open_, close) * np.exp(-lo[pick])
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol[pick]}, index=df.index)
