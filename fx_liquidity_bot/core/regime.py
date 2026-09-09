import pandas as pd


def detect_regime(df: pd.DataFrame, cfg) -> pd.Series:
    """Trend/range classification: EMA-slow slope sets direction, ADX confirms
    the move actually has trend strength (otherwise it's a range/chop)."""
    ema_slow = df["ema_slow"]
    slope = ema_slow.diff(cfg.regime_slope_lookback) / cfg.regime_slope_lookback
    slope_pct = slope / df["close"]
    trending = df["adx"] >= cfg.adx_trend_min

    regime = pd.Series("range", index=df.index)
    up = (slope_pct > cfg.regime_slope_min_pct) & (df["close"] > ema_slow) & trending
    down = (slope_pct < -cfg.regime_slope_min_pct) & (df["close"] < ema_slow) & trending
    regime[up] = "up"
    regime[down] = "down"
    return regime
