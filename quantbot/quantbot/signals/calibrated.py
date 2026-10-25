"""Moteur de signaux v2 : détecteurs flous -> scores de direction -> espérance CALIBRÉE -> décision.

La décision ne repose plus sur un seuil de confiance arbitraire : on trade seulement si l'espérance nette
apprise (hors période d'évaluation) dépasse une marge, sinon on s'abstient.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..config import Settings
from ..core.calibration import CalibrationModel
from ..patterns.scanner import PatternScanner
from .engine import Signal
from .scoring import direction_scores, floored_atr


class CalibratedSignalEngine:
    def __init__(self, settings: Settings, model: CalibrationModel) -> None:
        self.settings = settings
        self.model = model
        self.scanner = PatternScanner(settings)

    def evaluate(self, window: pd.DataFrame, htf: Optional[pd.DataFrame] = None) -> Optional[Signal]:
        matches = self.scanner.scan(window)
        bull, bear = direction_scores(matches, self.settings.signals)
        decision = self.model.decide(bull, bear)
        if decision is None:
            return None
        direction, ev = decision
        atr = floored_atr(self.scanner.last_context, self.settings.signals)
        chosen = sorted((m for m in matches if m.direction == direction), key=lambda m: -m.score)[:5]
        return Signal(direction, float(np.clip(ev, 0.0, 1.0)), float(window["close"].iloc[-1]), atr,
                      window.index[-1], chosen, [f"espérance calibrée {ev:+.3f} R"])
