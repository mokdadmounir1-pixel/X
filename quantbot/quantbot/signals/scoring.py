"""Scores de direction partagés par l'ENTRAÎNEMENT (calibration) et l'EXÉCUTION : une seule définition."""
from __future__ import annotations

import numpy as np

from ..config import SignalConfig
from ..patterns.base import MarketContext, PatternMatch


def direction_scores(matches: list[PatternMatch], cfg: SignalConfig) -> tuple[float, float]:
    """(score haussier, score baissier) dans [0,1] : meilleur score pondéré par catégorie + bonus de confluence.

    Pas de seuil de décision ici : c'est la calibration qui dira ce que vaut chaque niveau de score.
    """
    out = []
    for direction in ("bullish", "bearish"):
        confs, cats = [], set()
        for m in matches:
            if m.direction != direction:
                continue
            w = cfg.category_weights.get(m.category, 1.0)
            confs.append(m.score * w * (1.0 if m.confirmed else cfg.unconfirmed_penalty))
            cats.add(m.category)
        out.append(0.0 if not confs else min(1.0, max(confs) + cfg.confluence_bonus * (len(cats) - 1)))
    return out[0], out[1]


def floored_atr(ctx: MarketContext, cfg: SignalConfig, idx: int = -1) -> float:
    """ATR à la barre idx, relevé à `atr_floor_frac` x médiane des 200 barres précédentes (marché mince)."""
    n = ctx.n
    i = idx if idx >= 0 else n + idx
    atr = float(ctx.atr[i])
    if cfg.atr_floor_frac > 0:
        win = ctx.atr[max(0, i - 199): i + 1]
        if np.isfinite(win).any():
            atr = max(atr, cfg.atr_floor_frac * float(np.nanmedian(win)))
    return atr
