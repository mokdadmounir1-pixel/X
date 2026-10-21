"""Market data: CSV, ccxt (several exchanges, paginated, cached), else synthetic (flagged)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .synth import make_ohlcv

CACHE = Path(__file__).resolve().parents[1] / "data" / "cache"
EXCHANGES = ["binance", "bybit", "okx", "kraken", "coinbase", "kucoin"]


def from_ccxt(symbol="BTC/USDT", timeframe="1m", bars=30000):
    import ccxt
    last = None
    for ex_id in EXCHANGES:
        try:
            ex = getattr(ccxt, ex_id)({"enableRateLimit": True, "timeout": 8000})
            ms = ex.parse_timeframe(timeframe) * 1000
            since = ex.milliseconds() - bars * ms
            rows = []
            while len(rows) < bars:
                chunk = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
                if not chunk:
                    break
                rows += chunk
                since = chunk[-1][0] + ms
            df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).drop_duplicates("ts")
            df.index = pd.to_datetime(df.pop("ts"), unit="ms")
            CACHE.mkdir(parents=True, exist_ok=True)
            df.to_csv(CACHE / f"{ex_id}_{symbol.replace('/', '')}_{timeframe}.csv")
            return df, f"{ex_id}:{symbol}"
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"no exchange reachable ({last})")


def load(csv=None, symbol=None, bars=30000):
    if csv:
        df = pd.read_csv(csv, index_col=0, parse_dates=True)
        df.columns = [c.lower() for c in df.columns]
        return df, f"csv:{Path(csv).name}"
    if symbol:
        try:
            return from_ccxt(symbol, bars=bars)
        except Exception as e:  # noqa: BLE001
            print(f"[data] live fetch failed ({e}); falling back to synthetic")
    return make_ohlcv(bars), "synthetic"
