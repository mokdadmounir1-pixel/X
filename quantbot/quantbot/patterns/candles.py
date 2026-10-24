"""Chandeliers (photo « Candlesticks Signals »), version haussière + miroir.

Chaque `shape` renvoie (score_de_forme, détails) ou None si une condition
dure échoue (ex. mauvaise couleur de bougie). Le score final mélange la forme
et le contexte (tendance baissière préalable, pondération `context_weight`).
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from ..config import DetectionConfig, ToleranceConfig
from .base import MarketContext, PatternDetector, PatternMatch
from .tolerance import deviation_score, soft_ge, soft_le, weighted_mean

Shape = Callable[[MarketContext, int, float, ToleranceConfig], Optional[tuple[float, dict]]]


def _ohlc(ctx: MarketContext, i: int):
    return ctx.open[i], ctx.high[i], ctx.low[i], ctx.close[i]


def _hammer(ctx, i, atr, tol):
    o, h, l, c = _ohlc(ctx, i)
    rng = h - l
    if rng <= 0:
        return None
    body = abs(c - o)
    lower, upper = min(o, c) - l, h - max(o, c)
    ratio = lower / max(body, 0.02 * rng)
    parts = [
        (soft_ge(ratio, 2.0, tol), 2.0),
        (soft_le(upper / rng, 0.15, tol, scale=0.5), 1.0),
        (soft_le(body / rng, 0.4, tol, scale=0.5), 1.0),
        (soft_ge(rng / atr, 0.6, tol), 0.5),
    ]
    return weighted_mean(parts), {"lower_to_body": round(float(ratio), 2)}


def _dragonfly(ctx, i, atr, tol):
    o, h, l, c = _ohlc(ctx, i)
    rng = h - l
    if rng <= 0:
        return None
    parts = [
        (soft_le(abs(c - o) / rng, 0.1, tol, scale=0.5), 1.0),
        (soft_ge((min(o, c) - l) / rng, 0.6, tol), 2.0),
        (soft_le((h - max(o, c)) / rng, 0.1, tol, scale=0.5), 1.0),
        (soft_ge(rng / atr, 0.6, tol), 0.5),
    ]
    return weighted_mean(parts), {}


def _harami_core(ctx, i0, i1, atr, tol) -> Optional[float]:
    o0, c0 = ctx.open[i0], ctx.close[i0]
    o1, c1 = ctx.open[i1], ctx.close[i1]
    if c0 >= o0:
        return None
    body0 = o0 - c0
    if c1 < o1 - 0.1 * body0:
        return None
    overshoot = max(0.0, max(o1, c1) - o0, c0 - min(o1, c1)) / body0
    size = abs(c1 - o1) / body0
    return weighted_mean([
        (soft_ge(body0 / atr, 0.8, tol), 1.0),
        (deviation_score(overshoot, tol), 2.0),
        (soft_le(size, 0.6, tol, scale=1.0), 1.0),
    ])


def _harami(ctx, i, atr, tol):
    s = _harami_core(ctx, i - 1, i, atr, tol)
    return None if s is None else (s, {})


def _piercing(ctx, i, atr, tol):
    o0, c0 = ctx.open[i - 1], ctx.close[i - 1]
    o1, c1 = ctx.open[i], ctx.close[i]
    if c0 >= o0 or c1 <= o1:
        return None
    body0 = o0 - c0
    mid = (o0 + c0) / 2
    return weighted_mean([
        (soft_ge(body0 / atr, 0.8, tol), 1.0),
        (soft_le(o1, c0, tol, scale=body0), 1.0),
        (soft_ge(c1, mid, tol, scale=body0), 2.0),
        (soft_le(c1, o0, tol, scale=body0), 1.0),
    ]), {}


def _morning_star(ctx, i, atr, tol):
    o0, c0 = ctx.open[i - 2], ctx.close[i - 2]
    o1, c1 = ctx.open[i - 1], ctx.close[i - 1]
    o2, c2 = ctx.open[i], ctx.close[i]
    if c0 >= o0 or c2 <= o2:
        return None
    body0 = o0 - c0
    return weighted_mean([
        (soft_ge(body0 / atr, 0.8, tol), 1.0),
        (soft_le(abs(c1 - o1) / body0, 0.35, tol, scale=0.5), 1.5),
        (soft_le(max(o1, c1), c0, tol, scale=body0), 1.0),
        (soft_ge(c2, (o0 + c0) / 2, tol, scale=body0), 2.0),
    ]), {}


def _soldiers(ctx, i, atr, tol):
    idx = [i - 2, i - 1, i]
    if any(ctx.close[j] <= ctx.open[j] for j in idx):
        return None
    parts = []
    for k, j in enumerate(idx):
        body = ctx.close[j] - ctx.open[j]
        parts.append((soft_ge(body / atr, 0.6, tol), 1.0))
        parts.append((soft_le((ctx.high[j] - ctx.close[j]) / body, 0.3, tol, scale=0.5), 0.5))
        if k:
            p = idx[k - 1]
            body_p = ctx.close[p] - ctx.open[p]
            overshoot = max(0.0, ctx.open[p] - ctx.open[j], ctx.open[j] - ctx.close[p]) / body_p
            parts.append((deviation_score(overshoot, tol), 1.0))
            parts.append((soft_ge(ctx.close[j], ctx.close[p], tol, scale=atr), 1.5))
    return weighted_mean(parts), {}


def _outside_up(ctx, i, atr, tol):
    o0, c0 = ctx.open[i - 2], ctx.close[i - 2]
    o1, c1 = ctx.open[i - 1], ctx.close[i - 1]
    o2, c2 = ctx.open[i], ctx.close[i]
    if c0 >= o0 or c1 <= o1 or c2 <= o2:
        return None
    body0 = o0 - c0
    return weighted_mean([
        (soft_le(o1, c0, tol, scale=body0), 1.0),
        (soft_ge(c1, o0, tol, scale=body0), 2.0),
        (soft_ge(c2, c1, tol, scale=atr), 1.5),
        (soft_ge(body0 / atr, 0.3, tol), 0.5),
    ]), {}


def _inside_up(ctx, i, atr, tol):
    h = _harami_core(ctx, i - 2, i - 1, atr, tol)
    o0, c0 = ctx.open[i - 2], ctx.close[i - 2]
    if h is None or ctx.close[i] <= ctx.open[i]:
        return None
    body0 = o0 - c0
    return weighted_mean([
        (h, 2.0),
        (soft_ge(ctx.close[i], o0, tol, scale=body0), 2.0),
        (soft_ge(ctx.close[i], ctx.close[i - 1], tol, scale=atr), 1.0),
    ]), {}


def _kicker(ctx, i, atr, tol):
    o0, c0 = ctx.open[i - 1], ctx.close[i - 1]
    o1, c1 = ctx.open[i], ctx.close[i]
    if c0 >= o0 or c1 <= o1:
        return None
    body0 = o0 - c0
    return weighted_mean([
        (soft_ge(o1, o0, tol, scale=body0), 2.0),
        (soft_ge((c1 - o1) / atr, 0.8, tol), 1.0),
        (soft_ge(body0 / atr, 0.5, tol), 0.5),
    ]), {}


def _abandoned_baby(ctx, i, atr, tol):
    o0, c0, l0 = ctx.open[i - 2], ctx.close[i - 2], ctx.low[i - 2]
    o1, h1, l1, c1 = _ohlc(ctx, i - 1)
    o2, c2, l2 = ctx.open[i], ctx.close[i], ctx.low[i]
    rng1 = h1 - l1
    if c0 >= o0 or c2 <= o2 or rng1 <= 0:
        return None
    body0 = o0 - c0
    return weighted_mean([
        (soft_le(abs(c1 - o1) / rng1, 0.1, tol, scale=0.5), 1.5),
        (soft_le(h1, l0, tol, scale=body0), 1.5),
        (soft_ge(l2, h1, tol, scale=body0), 1.5),
        (soft_ge(body0 / atr, 0.8, tol), 1.0),
    ]), {}


class CandleDetector(PatternDetector):
    category = "candle"

    def __init__(self, tol: ToleranceConfig, det: DetectionConfig, family: str, name_bull: str,
                 name_bear: str, bars: int, shape: Shape) -> None:
        super().__init__(tol, det)
        self.family, self.name_bull, self.name_bear = family, name_bull, name_bear
        self.bars, self.shape = bars, shape

    def detect_bullish(self, ctx: MarketContext) -> list[PatternMatch]:
        n = ctx.n
        start = n - self.bars
        ref = start - 1
        if ref - self.det.context_bars < 0:
            return []
        atr = ctx.atr[ref]
        if not np.isfinite(atr) or atr <= 0:
            return []
        res = self.shape(ctx, n - 1, float(atr), self.tol)
        if res is None or res[0] <= 0:
            return []
        shape_score, details = res
        move = (ctx.close[ref] - ctx.close[ref - self.det.context_bars]) / atr
        ctx_score = float(np.clip(-move / self.det.context_move_atr, 0.0, 1.0))
        w = self.det.context_weight
        details = {**details, "shape": round(shape_score, 3), "context": round(ctx_score, 3)}
        return [PatternMatch(self.name_bull, self.category, "bullish", (1 - w) * shape_score + w * ctx_score,
                             start, n - 1, True, details,
                             [(n - 1, float(ctx.close[n - 1]))])]


CANDLE_SPECS: list[tuple[str, str, str, int, Shape]] = [
    ("hammer", "hammer", "shooting_star", 1, _hammer),
    ("dragonfly_doji", "dragonfly_doji", "gravestone_doji", 1, _dragonfly),
    ("harami", "bullish_harami", "bearish_harami", 2, _harami),
    ("piercing", "piercing_line", "dark_cloud_cover", 2, _piercing),
    ("morning_star", "morning_star", "evening_star", 3, _morning_star),
    ("soldiers", "three_white_soldiers", "three_black_crows", 3, _soldiers),
    ("outside_up", "three_outside_up", "three_outside_down", 3, _outside_up),
    ("inside_up", "three_inside_up", "three_inside_down", 3, _inside_up),
    ("kicker", "bullish_kicker", "bearish_kicker", 2, _kicker),
    ("abandoned_baby", "bullish_abandoned_baby", "bearish_abandoned_baby", 3, _abandoned_baby),
]


def build_candle_detectors(tol: ToleranceConfig, det: DetectionConfig) -> list[CandleDetector]:
    return [CandleDetector(tol, det, *spec) for spec in CANDLE_SPECS]
