from dataclasses import dataclass, field

from .instruments import PAIRS


@dataclass
class SessionWindow:
    name: str
    start_hour_utc: int
    end_hour_utc: int  # end < start means the window wraps past midnight UTC


DEFAULT_SESSIONS = [
    SessionWindow("sydney", 21, 6),
    SessionWindow("tokyo", 0, 9),
    SessionWindow("london", 7, 16),
    SessionWindow("new_york", 12, 21),
]

DEFAULT_MAX_SPREAD_PIPS = {
    "EURUSD": 1.5, "GBPUSD": 2.0, "USDJPY": 1.5, "AUDUSD": 1.8,
    "USDCAD": 2.0, "USDCHF": 2.0, "NZDUSD": 2.2,
}

DEFAULT_TYPICAL_SPREAD_PIPS = {
    "EURUSD": 0.8, "GBPUSD": 1.2, "USDJPY": 0.9, "AUDUSD": 1.0,
    "USDCAD": 1.3, "USDCHF": 1.3, "NZDUSD": 1.5,
}


@dataclass
class ScoreWeights:
    """Weights for each setup-quality factor. Need not sum to exactly 100 --
    the final score is renormalized to a 0-100 scale automatically."""
    sweep_quality: float = 15
    displacement_quality: float = 20
    fvg_quality: float = 10
    regime_alignment: float = 15
    volatility: float = 10
    momentum: float = 10
    liquidity_room: float = 10
    reward_risk: float = 5
    spread: float = 5


@dataclass
class StrategyConfig:
    pairs: list = field(default_factory=lambda: list(PAIRS))
    timeframe: str = "M1"

    # --- regime filter ---
    ema_fast: int = 20
    ema_slow: int = 50
    regime_slope_lookback: int = 20
    regime_slope_min_pct: float = 0.0003  # min |EMA slope| / price to call it trending
    adx_period: int = 14
    adx_trend_min: float = 20.0

    # --- indicators ---
    atr_period: int = 14
    rsi_period: int = 14

    # --- liquidity detection ---
    swing_fractal_width: int = 3          # bars each side required to confirm a swing point
    structure_lookback: int = 5           # bars used as the "local structure" break reference
    recent_extreme_lookback: int = 20     # rolling N-bar high/low used as a dynamic liquidity source
    liquidity_max_age_bars: int = 1500    # drop unswept levels older than this
    session_windows: list = field(default_factory=lambda: list(DEFAULT_SESSIONS))

    # --- sweep ---
    sweep_confirmation_bars: int = 3      # bars allowed for price to reintegrate after a breach
    sweep_min_pip_breach: float = 0.5     # min breach size (pips) to count as a real liquidity take

    # --- displacement ---
    displacement_max_bars: int = 5
    displacement_atr_mult: float = 1.3
    displacement_min_body_ratio: float = 0.55
    displacement_break_structure: bool = True

    # --- fair value gap ---
    fvg_min_size_atr_mult: float = 0.15
    fvg_retest_max_bars: int = 30
    fvg_retest_requires_close_inside: bool = False
    fvg_pick: str = "first"               # "first" or "largest"

    # --- momentum confirmation ---
    rsi_long_max: float = 65.0            # skip longs if RSI already overbought at the retest
    rsi_short_min: float = 35.0
    require_rejection_candle: bool = True

    # --- scoring ---
    score_weights: ScoreWeights = field(default_factory=ScoreWeights)
    score_threshold: float = 80.0

    # --- stop loss / take profit ---
    sl_atr_buffer_mult: float = 0.25
    min_rr: float = 1.5
    max_target_atr_mult: float = 6.0      # cap on how far a min-RR fallback target may reach

    # --- costs / execution ---
    max_spread_pips: dict = field(default_factory=lambda: dict(DEFAULT_MAX_SPREAD_PIPS))
    typical_spread_pips: dict = field(default_factory=lambda: dict(DEFAULT_TYPICAL_SPREAD_PIPS))
    commission_per_lot: float = 7.0       # round-turn USD per standard lot
    slippage_pips: float = 0.2

    # --- risk management ---
    risk_per_trade_pct: float = 0.5
    max_daily_loss_pct: float = 2.0
    max_trades_per_day: int = 10
    max_concurrent_trades: int = 3
    max_drawdown_pct: float = 10.0
    max_consecutive_losses: int = 4

    initial_equity: float = 10_000.0

    def apply_preset(self, name: str) -> None:
        """Convenience presets validated in the 10-scenario stress test
        (see README.md > 'Stress test: permissif vs sélectif'). 'selective'
        trades ~4-5x less often than the defaults but showed a lower and
        more consistent drawdown and a better average return across
        independent synthetic market histories -- at the cost of noisier
        per-scenario win rates from the smaller trade counts involved.
        These are starting points, not tuned optima -- re-validate on real
        historical data before trusting them with capital."""
        if name == "permissive":
            self.score_threshold, self.min_rr, self.max_trades_per_day = 50, 1.5, 10
        elif name == "selective":
            self.score_threshold, self.min_rr, self.max_trades_per_day = 70, 2.0, 5
        else:
            raise ValueError(f"Unknown preset: {name!r} (expected 'permissive' or 'selective')")
