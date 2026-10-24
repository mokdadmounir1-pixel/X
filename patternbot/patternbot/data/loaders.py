"""Sources de données : CSV, synthétique, ccxt, MetaTrader 5 (optionnels)."""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..exceptions import DataFetchError, DataValidationError
from ..logging_utils import get_logger
from .validation import validate_ohlcv

log = get_logger("data.loaders")


def load_csv(path: str | Path, repair: bool = False) -> pd.DataFrame:
    try:
        raw = pd.read_csv(path)
    except FileNotFoundError as exc:
        raise DataFetchError(f"CSV introuvable : {path}") from exc
    except Exception as exc:  # parsing
        raise DataValidationError(f"CSV illisible ({path}) : {exc}") from exc
    raw.columns = [str(c).lower() for c in raw.columns]
    ts = next((c for c in ("timestamp", "time", "date", "datetime") if c in raw.columns), None)
    if ts is None:
        raise DataValidationError("Colonne temporelle absente (timestamp/time/date/datetime)")
    unit = "ms" if pd.api.types.is_numeric_dtype(raw[ts]) and raw[ts].iloc[0] > 1e11 else None
    raw.index = pd.to_datetime(raw[ts], unit=unit)
    return validate_ohlcv(raw.drop(columns=[ts]), repair=repair)


def generate_synthetic(
    n: int = 1500, seed: int = 7, start_price: float = 100.0, freq: str = "1h", start: str = "2024-01-01"
) -> pd.DataFrame:
    """Marché synthétique avec changements de régime (tendance / volatilité)."""
    rng = np.random.default_rng(seed)
    rows, price, produced = [], start_price, 0
    while produced < n:
        seg = int(rng.integers(40, 160))
        mu, sigma = rng.normal(0, 0.0008), rng.uniform(0.004, 0.012)
        for _ in range(min(seg, n - produced)):
            o = price
            c = o * float(np.exp(rng.normal(mu, sigma)))
            wick = abs(rng.normal(0, sigma * 0.6))
            h = max(o, c) * (1 + wick * rng.random())
            lo = min(o, c) * (1 - wick * rng.random())
            rows.append((o, h, lo, c, float(rng.uniform(500, 1500))))
            price = c
            produced += 1
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    df.index = pd.date_range(start, periods=n, freq=freq)
    return validate_ohlcv(df)


def fetch_ccxt(exchange_id: str, symbol: str, timeframe: str = "1h", limit: int = 500,
               retries: int = 3, backoff: float = 2.0) -> pd.DataFrame:
    try:
        import ccxt  # type: ignore
    except ImportError as exc:
        raise DataFetchError("ccxt non installé (pip install ccxt)") from exc
    klass = getattr(ccxt, exchange_id, None)
    if klass is None:
        raise DataFetchError(f"Exchange ccxt inconnu : {exchange_id}")
    exchange = klass({"enableRateLimit": True})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df.index = pd.to_datetime(df.pop("timestamp"), unit="ms")
            return validate_ohlcv(df, repair=True)
        except Exception as exc:  # réseau, rate limit...
            last = exc
            log.warning("fetch_ohlcv tentative %d/%d échouée : %s", attempt + 1, retries, exc)
            time.sleep(backoff ** attempt)
    raise DataFetchError(f"Echec ccxt {exchange_id} {symbol} : {last}") from last


def fetch_mt5(symbol: str, timeframe: str = "H1", bars: int = 1000, utc_offset_hours: int = 0,
              drop_forming: bool = True) -> pd.DataFrame:
    """Historique MetaTrader 5 (paquet MetaTrader5, Windows uniquement).

    La barre 0 de MT5 est en cours de formation : elle est retirée par défaut
    (jamais de décision sur une bougie non clôturée). L'heure serveur est ramenée en UTC.
    """
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:
        raise DataFetchError("Paquet MetaTrader5 indisponible (Windows + terminal MT5 requis)") from exc
    if not mt5.initialize():
        raise DataFetchError(f"Initialisation MT5 impossible : {mt5.last_error()}")
    try:
        tf = getattr(mt5, f"TIMEFRAME_{timeframe}", None)
        if tf is None:
            raise DataFetchError(f"Timeframe MT5 inconnu : {timeframe}")
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
        if rates is None or len(rates) == 0:
            raise DataFetchError(f"Aucune donnée MT5 pour {symbol}")
        df = pd.DataFrame(rates)
        df.index = pd.to_datetime(df["time"], unit="s") - pd.Timedelta(hours=utc_offset_hours)
        df["volume"] = df.get("tick_volume", 0)
        if drop_forming:
            df = df.iloc[:-1]
        return validate_ohlcv(df[["open", "high", "low", "close", "volume"]], repair=True)
    finally:
        mt5.shutdown()


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = df.resample(rule).agg(agg).dropna(subset=["open", "close"])
    return out
