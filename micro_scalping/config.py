from dataclasses import dataclass


@dataclass
class ScalpingConfig:
    # Trend filter (fast/slow EMA crossover state)
    ema_fast: int = 9
    ema_slow: int = 21

    # Pullback trigger
    rsi_period: int = 7
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0

    # Volatility regime filter
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 14
    atr_min_pct: float = 0.0004  # skip bars where ATR/price is below this (dead market)

    # Risk management (ATR-based, adapts to volatility instead of fixed pips)
    sl_atr_mult: float = 1.2
    tp_atr_mult: float = 2.0  # reward:risk ~= 1.67:1
    risk_per_trade_pct: float = 0.5  # % of equity risked per trade
    max_trades_per_day: int = 40
    cooldown_bars: int = 3  # bars to sit out after closing a trade

    # Costs
    commission_pct: float = 0.04  # per side (e.g. Binance taker fee)
    slippage_pct: float = 0.02

    initial_equity: float = 10_000.0
