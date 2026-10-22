from __future__ import annotations

import pandas as pd

from .config import ScalpingConfig
from .indicators import atr, bollinger_bands, ema, rsi


def add_indicators(df: pd.DataFrame, cfg: ScalpingConfig) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = ema(df["close"], cfg.ema_fast)
    df["ema_slow"] = ema(df["close"], cfg.ema_slow)
    df["rsi"] = rsi(df["close"], cfg.rsi_period)
    df["atr"] = atr(df, cfg.atr_period)
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bollinger_bands(
        df["close"], cfg.bb_period, cfg.bb_std
    )
    df["atr_pct"] = df["atr"] / df["close"]
    return df


def generate_signal(row, prev_row, cfg: ScalpingConfig) -> str | None:
    """Trend-aligned pullback entry: trade *with* the EMA trend, triggered by an
    RSI reversion out of oversold/overbought while price is still on the pullback
    side of the Bollinger mid-band. Skips low-volatility bars to avoid chop."""
    if pd.isna(row.ema_slow) or pd.isna(row.rsi) or pd.isna(row.bb_mid):
        return None
    if row.atr_pct < cfg.atr_min_pct:
        return None

    uptrend = row.ema_fast > row.ema_slow
    downtrend = row.ema_fast < row.ema_slow

    rsi_cross_up = prev_row.rsi <= cfg.rsi_oversold < row.rsi
    rsi_cross_down = prev_row.rsi >= cfg.rsi_overbought > row.rsi

    pullback_zone_long = row.close <= row.bb_mid
    pullback_zone_short = row.close >= row.bb_mid

    if uptrend and rsi_cross_up and pullback_zone_long:
        return "long"
    if downtrend and rsi_cross_down and pullback_zone_short:
        return "short"
    return None
