"""Stratégies à règles explicites : événements causaux datés -> signaux pour le moteur unique.

Chaque stratégie est une machine à états qui parcourt les barres dans l'ordre et n'émet un événement à la barre t
qu'avec des données <= t. Garantie testée : générer les événements sur un préfixe des données donne exactement les
mêmes événements que sur la série complète (aucune fuite).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from ..config import Settings
from ..indicators.core import atr_np
from ..patterns.base import PatternMatch
from ..signals.engine import Signal


@dataclass
class Event:
    ts: pd.Timestamp
    direction: str  # bullish | bearish
    stop: float
    target: Optional[float] = None  # None = cible par défaut (reward_risk du risque)
    name: str = ""
    meta: dict = field(default_factory=dict)


def atr_series(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    return atr_np(df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float), period)


class EventSignalEngine:
    """Sert les événements pré-calculés au moteur ; `evaluate` ne regarde que la dernière barre de la fenêtre."""

    def __init__(self, settings: Settings, events: list[Event]) -> None:
        self.settings = settings
        self.by_ts: dict = {}
        for e in events:
            self.by_ts.setdefault(e.ts, e)  # un seul événement par barre (le premier)

    def evaluate(self, window: pd.DataFrame, htf=None) -> Optional[Signal]:
        ev = self.by_ts.get(window.index[-1])
        if ev is None:
            return None
        a = atr_series(window.tail(300), self.settings.detection.atr_period)
        atr = float(a[-1]) if np.isfinite(a[-1]) else float("nan")
        frac = self.settings.signals.atr_floor_frac
        if frac > 0 and np.isfinite(a).any():
            atr = max(atr, frac * float(np.nanmedian(a[-200:])))
        m = PatternMatch(ev.name or "event", "event", ev.direction, 0.9, 0, 1, True, ev.meta)
        return Signal(ev.direction, 0.9, float(window["close"].iloc[-1]), atr, window.index[-1], [m],
                      [ev.name], stop_price=ev.stop, take_profit_price=ev.target)
