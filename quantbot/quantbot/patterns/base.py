"""Contexte de marché (numpy), résultat de détection et classe de base."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..config import DetectionConfig, ToleranceConfig
from ..indicators.core import atr_np
from ..indicators.structure import Pivot, swing_points


@dataclass
class PatternMatch:
    name: str
    category: str  # candle | chart | harmonic
    direction: str  # bullish | bearish
    score: float  # similarité 0..1
    start_idx: int
    end_idx: int
    confirmed: bool = True
    details: dict[str, Any] = field(default_factory=dict)
    points: list[tuple[int, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.score = float(min(1.0, max(0.0, self.score)))


@dataclass
class MarketContext:
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    atr: np.ndarray
    pivots: list[Pivot]
    index: Any = None
    inverted: bool = False

    @property
    def n(self) -> int:
        return len(self.close)

    @classmethod
    def from_frame(cls, df: pd.DataFrame, order: int = 3, atr_period: int = 14) -> "MarketContext":
        o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
        v = df["volume"].to_numpy(dtype=float) if "volume" in df else np.zeros(len(df))
        return cls(o, h, l, c, v, atr_np(h, l, c, atr_period), swing_points(h, l, order), df.index)

    def invert(self) -> "MarketContext":
        """Miroir des prix : un détecteur haussier y trouve le pattern baissier."""
        flipped = [Pivot(p.idx, -p.price, "L" if p.kind == "H" else "H") for p in self.pivots]
        return MarketContext(-self.open, -self.low, -self.high, -self.close, self.volume,
                             self.atr, flipped, self.index, not self.inverted)


class PatternDetector(ABC):
    """Un détecteur n'écrit que la version haussière ; la baissière vient du miroir."""

    family: str = ""
    name_bull: str = ""
    name_bear: str = ""
    category: str = ""

    def __init__(self, tol: ToleranceConfig, det: DetectionConfig) -> None:
        self.tol = tol
        self.det = det

    @abstractmethod
    def detect_bullish(self, ctx: MarketContext) -> list[PatternMatch]:
        """Patterns haussiers terminant à la dernière barre du contexte."""

    def detect(self, ctx: MarketContext, inv: Optional[MarketContext] = None) -> list[PatternMatch]:
        inv = inv if inv is not None else ctx.invert()
        out = list(self.detect_bullish(ctx))
        for m in self.detect_bullish(inv):
            m.name = self.name_bear or m.name
            m.direction = "bearish"
            m.points = [(i, -p) for i, p in m.points]
            out.append(m)
        return out
