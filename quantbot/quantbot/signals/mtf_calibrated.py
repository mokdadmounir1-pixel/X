"""Moteur de signaux v3 : scores flous x contexte multi-timeframe -> espérance calibrée PAR ÉTAT de tendance HTF."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..config import Settings
from ..core.calibration import StratifiedModel
from ..patterns.scanner import PatternScanner
from .engine import Signal
from .scoring import direction_scores, floored_atr


class MTFCalibratedSignalEngine:
    def __init__(self, settings: Settings, model: StratifiedModel, bias: pd.Series) -> None:
        self.settings, self.model, self.bias = settings, model, bias
        self.scanner = PatternScanner(settings)

    def evaluate(self, window: pd.DataFrame, htf: Optional[pd.DataFrame] = None) -> Optional[Signal]:
        ts = window.index[-1]
        state = int(self.bias.get(ts, 0))  # biais PRÉ-CALCULÉ de façon causale (HTF terminées seulement)
        matches = self.scanner.scan(window)
        bull, bear = direction_scores(matches, self.settings.signals)
        decision = self.model.decide(bull, bear, state)
        if decision is None:
            return None
        direction, ev = decision
        atr = floored_atr(self.scanner.last_context, self.settings.signals)
        chosen = sorted((m for m in matches if m.direction == direction), key=lambda m: -m.score)[:5]
        return Signal(direction, float(np.clip(ev, 0.0, 1.0)), float(window["close"].iloc[-1]), atr, ts, chosen,
                      [f"état HTF {state:+d} · espérance calibrée {ev:+.3f} R"])
