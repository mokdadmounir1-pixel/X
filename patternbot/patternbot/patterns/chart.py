"""Figures chartistes sur pivots confirmés (version haussière + miroir).

double bottom/top, tête-épaules inversé/classique, triangle ascendant/descendant.
Non couverts (feuille de route) : wedges, pennants, scallop, diamond, cup & handle, island.
"""
from __future__ import annotations

import numpy as np

from ..indicators.structure import Pivot
from .base import MarketContext, PatternDetector, PatternMatch
from .tolerance import deviation_score, soft_ge, weighted_mean


def recent_pivots(ctx: MarketContext, k: int, max_age: int):
    if len(ctx.pivots) < k:
        return None
    pv = ctx.pivots[-k:]
    if ctx.n - 1 - pv[-1].idx > max_age:
        return None
    return pv


def _valid_atr(ctx: MarketContext):
    atr = ctx.atr[-1]
    return float(atr) if np.isfinite(atr) and atr > 0 else None


def _pts(pv: list[Pivot]) -> list[tuple[int, float]]:
    return [(p.idx, p.price) for p in pv]


class DoubleBottom(PatternDetector):
    family, name_bull, name_bear, category = "double_bottom", "double_bottom", "double_top", "chart"

    def detect_bullish(self, ctx):
        pv = recent_pivots(ctx, 3, self.det.max_pivot_age)
        atr = _valid_atr(ctx)
        if pv is None or atr is None or [p.kind for p in pv] != ["L", "H", "L"]:
            return []
        l1, hi, l2 = pv
        height = hi.price - min(l1.price, l2.price)
        if height < self.det.min_height_atr * atr or l2.idx - l1.idx < 2 * self.det.min_bars_between:
            return []
        dev = abs(l1.price - l2.price) / height
        s_eq = deviation_score(dev, self.tol)
        if s_eq <= 0:
            return []
        score = weighted_mean([(s_eq, 0.85), (soft_ge(height / atr, 3.0, self.tol), 0.15)])
        return [PatternMatch(self.name_bull, self.category, "bullish", score, l1.idx, ctx.n - 1,
                             bool(ctx.close[-1] > hi.price),
                             {"low_gap_ratio": round(float(dev), 3), "neckline": float(hi.price)}, _pts(pv))]


class InverseHeadShoulders(PatternDetector):
    family, name_bull, name_bear, category = ("head_shoulders", "inverse_head_shoulders",
                                              "head_and_shoulders", "chart")

    def detect_bullish(self, ctx):
        pv = recent_pivots(ctx, 5, self.det.max_pivot_age)
        atr = _valid_atr(ctx)
        if pv is None or atr is None or [p.kind for p in pv] != ["L", "H", "L", "H", "L"]:
            return []
        ls, h1, head, h2, rs = pv
        neck = (h1.price + h2.price) / 2
        height = neck - head.price
        if height < self.det.min_height_atr * atr:
            return []
        depth = (min(ls.price, rs.price) - head.price) / height
        s_head = soft_ge(depth, 0.15, self.tol, scale=0.15)
        if s_head <= 0:
            return []
        s_sym = deviation_score(abs(ls.price - rs.price) / height, self.tol)
        s_neck = deviation_score(abs(h1.price - h2.price) / height, self.tol)
        score = weighted_mean([(s_head, 2.0), (s_sym, 1.5), (s_neck, 1.0),
                               (soft_ge(height / atr, 3.0, self.tol), 0.5)])
        return [PatternMatch(self.name_bull, self.category, "bullish", score, ls.idx, ctx.n - 1,
                             bool(ctx.close[-1] > neck),
                             {"head_depth": round(float(depth), 3), "neckline": float(neck)}, _pts(pv))]


class AscendingTriangle(PatternDetector):
    family, name_bull, name_bear, category = ("triangle", "ascending_triangle",
                                              "descending_triangle", "chart")

    def detect_bullish(self, ctx):
        pv = recent_pivots(ctx, 5, self.det.max_pivot_age) or recent_pivots(ctx, 4, self.det.max_pivot_age)
        atr = _valid_atr(ctx)
        if pv is None or atr is None:
            return []
        highs = [p for p in pv if p.kind == "H"]
        lows = [p for p in pv if p.kind == "L"]
        if len(highs) < 2 or len(lows) < 2:
            return []
        height = float(np.mean([p.price for p in highs])) - min(p.price for p in lows)
        if height < self.det.min_height_atr * atr:
            return []
        flat = (max(p.price for p in highs) - min(p.price for p in highs)) / height
        diffs = np.diff([p.price for p in lows])
        if (diffs <= 0).any():
            return []  # creux non strictement croissants
        rise = (lows[-1].price - lows[0].price) / height
        score = weighted_mean([(deviation_score(flat, self.tol), 1.5),
                               (soft_ge(rise, 0.2, self.tol, scale=0.2), 1.5),
                               (soft_ge(height / atr, 3.0, self.tol), 0.5)])
        resistance = max(p.price for p in highs)
        return [PatternMatch(self.name_bull, self.category, "bullish", score, pv[0].idx, ctx.n - 1,
                             bool(ctx.close[-1] > resistance),
                             {"flatness": round(float(flat), 3), "rise": round(float(rise), 3),
                              "resistance": float(resistance)}, _pts(pv))]
