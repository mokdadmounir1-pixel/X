"""Scores de direction pour TOUTES les barres (entraînement de la calibration).

Reproduit exactement ce que voit le moteur à l'exécution : fenêtre = segment continu courant, `window_bars`
dernières barres, mêmes détecteurs, même `direction_scores`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Settings
from ..patterns.scanner import PatternScanner
from ..signals.scoring import direction_scores
from .labels import _segments


def compute_scores(df: pd.DataFrame, settings: Settings) -> tuple[np.ndarray, np.ndarray]:
    bt = settings.backtest
    n = len(df)
    bull, bear = np.full(n, np.nan), np.full(n, np.nan)
    _, seg = _segments(df.index, bt.max_gap_hours)
    scanner = PatternScanner(settings)
    for t in range(n):
        if (t + 1) - seg[t] <= bt.warmup_bars:
            continue
        window = df.iloc[seg[t]: t + 1].tail(bt.window_bars)
        bull[t], bear[t] = direction_scores(scanner.scan(window), settings.signals)
    return bull, bear
