"""Orchestration des détecteurs : un seul passage, erreurs isolées et loggées."""
from __future__ import annotations

import pandas as pd

from ..config import Settings
from ..logging_utils import get_logger
from .base import MarketContext, PatternDetector, PatternMatch
from .candles import build_candle_detectors
from .chart import AscendingTriangle, DoubleBottom, InverseHeadShoulders
from .harmonic import build_harmonic_detectors

log = get_logger("patterns.scanner")


def build_detectors(settings: Settings) -> list[PatternDetector]:
    tol, det = settings.tolerance, settings.detection
    detectors: list[PatternDetector] = build_candle_detectors(tol, det)
    detectors += [DoubleBottom(tol, det), InverseHeadShoulders(tol, det), AscendingTriangle(tol, det)]
    detectors += build_harmonic_detectors(tol, det)
    if det.enabled is not None:
        wanted = set(det.enabled)
        detectors = [d for d in detectors if d.family in wanted]
    return detectors


class PatternScanner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.detectors = build_detectors(settings)
        self.errors = 0
        self.last_context: MarketContext | None = None

    def scan(self, df: pd.DataFrame) -> list[PatternMatch]:
        det = self.settings.detection
        ctx = MarketContext.from_frame(df, det.pivot_order, det.atr_period)
        self.last_context = ctx
        inv = ctx.invert()
        found: list[PatternMatch] = []
        for detector in self.detectors:
            try:
                found.extend(detector.detect(ctx, inv))
            except Exception:  # un détecteur défaillant ne doit pas stopper le bot
                self.errors += 1
                log.exception("Détecteur %s en échec", detector.family)
        kept = [m for m in found if m.score >= self.settings.tolerance.min_score]
        return sorted(kept, key=lambda m: -m.score)
