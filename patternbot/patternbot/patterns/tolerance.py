"""Logique floue : scores de similarité plutôt que correspondance binaire.

Tout part d'un écart relatif `dev` (0 = parfait) :
  dev <= tolerance_percentage            -> score 1
  dev >= deviation_threshold             -> score 0
  entre les deux                         -> décroissance linéaire
"""
from __future__ import annotations

from typing import Iterable, Optional

from ..config import ToleranceConfig

_EPS = 1e-12


def deviation_score(dev: float, tol: ToleranceConfig) -> float:
    if dev <= tol.tolerance_percentage:
        return 1.0
    if dev >= tol.deviation_threshold:
        return 0.0
    span = tol.deviation_threshold - tol.tolerance_percentage
    return 1.0 - (dev - tol.tolerance_percentage) / span


def _scale(value: Optional[float], ref: float) -> float:
    return abs(value) if value is not None else abs(ref)


def soft_eq(value: float, target: float, tol: ToleranceConfig, scale: Optional[float] = None) -> float:
    s = _scale(scale, target)
    if s < _EPS:
        return 1.0 if abs(value - target) < _EPS else 0.0
    return deviation_score(abs(value - target) / s, tol)


def soft_ge(value: float, threshold: float, tol: ToleranceConfig, scale: Optional[float] = None) -> float:
    """Score de `value >= threshold` (tolérant)."""
    if value >= threshold:
        return 1.0
    s = _scale(scale, threshold)
    if s < _EPS:
        return 0.0
    return deviation_score((threshold - value) / s, tol)


def soft_le(value: float, threshold: float, tol: ToleranceConfig, scale: Optional[float] = None) -> float:
    """Score de `value <= threshold` (tolérant)."""
    if value <= threshold:
        return 1.0
    s = _scale(scale, threshold)
    if s < _EPS:
        return 0.0
    return deviation_score((value - threshold) / s, tol)


def soft_range(value: float, lo: float, hi: float, tol: ToleranceConfig) -> float:
    """1 dans [lo, hi] ; sinon décroissance selon l'écart relatif au bord le plus proche."""
    if lo <= value <= hi:
        return 1.0
    edge = lo if value < lo else hi
    if abs(edge) < _EPS:
        return 0.0
    return deviation_score(abs(value - edge) / abs(edge), tol)


def weighted_mean(parts: Iterable[tuple[float, float]]) -> float:
    total = weight = 0.0
    for score, w in parts:
        total += score * w
        weight += w
    return total / weight if weight else 0.0
