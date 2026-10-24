"""Agrégation des patterns en un signal unique (direction + confiance)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..config import Settings
from ..indicators.core import ema
from ..logging_utils import get_logger
from ..patterns.base import PatternMatch
from ..patterns.scanner import PatternScanner

log = get_logger("signals")


@dataclass
class Signal:
    direction: str  # bullish | bearish
    confidence: float
    price: float
    atr: float
    timestamp: Any
    matches: list[PatternMatch]
    notes: list[str] = field(default_factory=list)

    @property
    def pattern_names(self) -> list[str]:
        return [m.name for m in self.matches]


def _trend(df: pd.DataFrame, fast: int, slow: int) -> Optional[str]:
    if len(df) < slow + 1:
        return None
    f, s = ema(df["close"], fast).iloc[-1], ema(df["close"], slow).iloc[-1]
    if not (np.isfinite(f) and np.isfinite(s)):
        return None
    return "bullish" if f > s else "bearish"


class SignalEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.scanner = PatternScanner(settings)

    def evaluate(self, df: pd.DataFrame, htf_df: Optional[pd.DataFrame] = None) -> Optional[Signal]:
        return self.build_signal(df, self.scanner.scan(df), htf_df)

    def build_signal(self, df: pd.DataFrame, matches: list[PatternMatch],
                     htf_df: Optional[pd.DataFrame] = None) -> Optional[Signal]:
        cfg = self.settings.signals
        by_dir: dict[str, list[tuple[float, PatternMatch]]] = {"bullish": [], "bearish": []}
        for m in matches:
            if cfg.require_confirmation and not m.confirmed:
                continue
            weight = cfg.category_weights.get(m.category, 1.0)
            conf = m.score * weight * (1.0 if m.confirmed else cfg.unconfirmed_penalty)
            by_dir[m.direction].append((conf, m))
        best = {d: max((c for c, _ in v), default=0.0) for d, v in by_dir.items()}
        if max(best.values()) <= 0:
            return None
        direction = max(best, key=best.get)
        other = "bearish" if direction == "bullish" else "bullish"
        if best[direction] - best[other] < cfg.min_edge:
            log.debug("Signal ambigu (bull=%.2f bear=%.2f)", best["bullish"], best["bearish"])
            return None

        chosen = sorted(by_dir[direction], key=lambda x: -x[0])
        categories = {m.category for _, m in chosen}
        conf = min(1.0, best[direction] + cfg.confluence_bonus * (len(categories) - 1))
        notes: list[str] = []

        if cfg.trend_filter != "none":
            ref = df if cfg.trend_filter == "ema" else htf_df
            trend = _trend(ref, cfg.ema_fast, cfg.ema_slow) if ref is not None else None
            if trend is not None and trend != direction:
                conf *= cfg.counter_trend_penalty
                notes.append(f"contre-tendance ({cfg.trend_filter})")
        if conf < cfg.min_confidence:
            return None

        ctx = self.scanner.last_context
        atr = float(ctx.atr[-1]) if ctx is not None else float("nan")
        return Signal(direction, conf, float(df["close"].iloc[-1]), atr, df.index[-1],
                      [m for _, m in chosen[:5]], notes)
