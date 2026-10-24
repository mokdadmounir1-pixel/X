"""Moteur de calcul des indicateurs (pandas / numpy)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, period: int) -> pd.Series:
    return s.rolling(period, min_periods=period).mean()


def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    out = 100 - 100 / (1 + gain / loss)
    return out.where(loss != 0, 100.0).where(gain.notna())


def stoch_rsi(s: pd.Series, rsi_period: int = 14, stoch_period: int = 14) -> pd.Series:
    r = rsi(s, rsi_period)
    lo, hi = r.rolling(stoch_period).min(), r.rolling(stoch_period).max()
    return (r - lo) / (hi - lo).replace(0, np.nan)


def true_range_np(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev = np.concatenate(([close[0]], close[:-1]))
    return np.maximum.reduce([high - low, np.abs(high - prev), np.abs(low - prev)])


def atr_np(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """ATR de Wilder ; NaN avant `period` barres."""
    n = len(close)
    out = np.full(n, np.nan)
    if n < period:
        return out
    tr = true_range_np(high, low, close)
    out[period - 1] = tr[:period].mean()
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return pd.Series(atr_np(df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(), period), index=df.index)


def volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return df["volume"] / sma(df["volume"], period).replace(0, np.nan)
