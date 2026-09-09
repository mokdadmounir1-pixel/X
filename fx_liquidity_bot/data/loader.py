from __future__ import annotations

import numpy as np
import pandas as pd

from ..instruments import BASE_PRICE, PIP_SIZE


def load_csv(path: str) -> pd.DataFrame:
    """Load OHLC(V) from a CSV with a time column plus open/high/low/close
    (and optionally volume/spread_pips). Any reasonable header casing/name
    for the time column ('time', 'date', 'datetime', or just the first
    column) is accepted."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    time_col = next((c for c in ("time", "date", "datetime") if c in df.columns), df.columns[0])
    df[time_col] = pd.to_datetime(df[time_col], utc=True)
    df = df.set_index(time_col).sort_index()

    keep = [c for c in ("open", "high", "low", "close", "volume", "spread_pips") if c in df.columns]
    missing = {"open", "high", "low", "close"} - set(keep)
    if missing:
        raise ValueError(f"CSV {path} is missing required column(s): {missing}")
    return df[keep]


def generate_synthetic_fx(pair: str, n_bars: int = 20_000, seed: int = 7, bar_minutes: int = 1) -> pd.DataFrame:
    """Regime-switching random walk in pips, with periodic injected
    fake-wick-then-impulse bursts so the sweep/displacement/FVG pipeline has
    real patterns to find. This is a synthetic self-test fixture, not a
    market simulator -- it has no claim to statistical realism, only to
    exercising the full pipeline end to end.

    `bar_minutes` lets you cover a multi-year span in far fewer bars (e.g.
    M15 instead of M1) for faster large-scale backtests -- the pipeline
    itself is timeframe-agnostic, it just reads whatever bars it's given."""
    pair_offset = sum(ord(c) for c in pair)  # stable across processes, unlike built-in hash()
    rng = np.random.default_rng(seed + pair_offset)
    pip = PIP_SIZE[pair]
    price = BASE_PRICE[pair]
    times = pd.date_range("2024-01-01", periods=n_bars, freq=f"{bar_minutes}min", tz="UTC")

    opens = np.empty(n_bars)
    highs = np.empty(n_bars)
    lows = np.empty(n_bars)
    closes = np.empty(n_bars)

    vol = pip * rng.uniform(1.5, 3.0) * np.sqrt(bar_minutes)
    trend_bias = 0.0
    bars_left = 0
    cur = price

    for i in range(n_bars):
        if bars_left <= 0:
            bars_left = int(rng.integers(200, 600))
            trend_bias = rng.choice([-1, 0, 1]) * pip * rng.uniform(0.05, 0.25)
        bars_left -= 1

        o = cur
        step = rng.normal(trend_bias, vol)

        if rng.random() < 0.004:
            sign = 1 if rng.random() < 0.5 else -1
            fake_wick = sign * pip * rng.uniform(3, 8)
            impulse = -sign * pip * rng.uniform(8, 20)
            c = o + impulse
            h = max(o, c, o + max(fake_wick, 0)) + pip * 0.5
            l = min(o, c, o + min(fake_wick, 0)) - pip * 0.5
        else:
            c = o + step
            wick = pip * rng.uniform(0.5, 2.0)
            h = max(o, c) + wick
            l = min(o, c) - wick

        opens[i], highs[i], lows[i], closes[i] = o, h, l, c
        cur = c

    volume = rng.uniform(50, 500, n_bars)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume}, index=times
    )


def generate_synthetic_universe(
    pairs: list[str], n_bars: int = 20_000, seed: int = 7, bar_minutes: int = 1
) -> dict[str, pd.DataFrame]:
    return {pair: generate_synthetic_fx(pair, n_bars, seed, bar_minutes) for pair in pairs}
