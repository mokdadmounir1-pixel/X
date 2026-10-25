"""Patterns harmoniques XABCD (Gartley, Bat, Butterfly, Crab).

Ratios standards issus de la fiche ; chaque ratio est une *plage* évaluée avec
tolérance (un ratio un peu hors plage reste partiellement valide).
b  : retracement de B sur XA          bc : retracement de C sur AB
cd : extension de CD par rapport à BC  d  : retracement/extension de D sur XA
"""
from __future__ import annotations

from .base import MarketContext, PatternDetector, PatternMatch
from .chart import _pts, _valid_atr, recent_pivots
from .tolerance import soft_range, weighted_mean

HARMONIC_RATIOS: dict[str, dict[str, tuple[float, float]]] = {
    "gartley": dict(b=(0.618, 0.618), bc=(0.382, 0.886), cd=(1.272, 1.618), d=(0.786, 0.786)),
    "bat": dict(b=(0.382, 0.500), bc=(0.382, 0.886), cd=(1.618, 2.618), d=(0.886, 0.886)),
    "butterfly": dict(b=(0.786, 0.786), bc=(0.382, 0.886), cd=(1.618, 2.618), d=(1.272, 1.272)),
    "crab": dict(b=(0.382, 0.618), bc=(0.382, 0.886), cd=(2.618, 3.618), d=(1.618, 1.618)),
}
_WEIGHTS = {"b": 1.5, "bc": 0.75, "cd": 1.0, "d": 2.0}


class HarmonicDetector(PatternDetector):
    category = "harmonic"

    def __init__(self, tol, det, kind: str) -> None:
        super().__init__(tol, det)
        self.kind = kind
        self.family = self.name_bull = self.name_bear = kind

    def detect_bullish(self, ctx: MarketContext) -> list[PatternMatch]:
        pv = recent_pivots(ctx, 5, self.det.max_pivot_age)
        atr = _valid_atr(ctx)
        if pv is None or atr is None or [p.kind for p in pv] != ["L", "H", "L", "H", "L"]:
            return []
        x, a, b, c, d = (p.price for p in pv)
        xa, ab, bc, cd = a - x, a - b, c - b, c - d
        if min(xa, ab, bc, cd) <= 0 or xa < self.det.min_height_atr * atr:
            return []
        ratios = {"b": ab / xa, "bc": bc / ab, "cd": cd / bc, "d": (a - d) / xa}
        spec = HARMONIC_RATIOS[self.kind]
        scores = {k: soft_range(ratios[k], *spec[k], self.tol) for k in ratios}
        score = weighted_mean((scores[k], _WEIGHTS[k]) for k in ratios)
        return [PatternMatch(self.kind, self.category, "bullish", score, pv[0].idx, ctx.n - 1,
                             bool(ctx.close[-1] > d + 0.5 * atr),
                             {"ratios": {k: round(float(v), 3) for k, v in ratios.items()}}, _pts(pv))]


def build_harmonic_detectors(tol, det) -> list[HarmonicDetector]:
    return [HarmonicDetector(tol, det, kind) for kind in HARMONIC_RATIOS]
