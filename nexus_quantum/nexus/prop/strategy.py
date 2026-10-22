"""Trend multi-actifs a cible de volatilite (TSMOM), barres journalieres.

Signal a la cloture t (donnees <= t uniquement), position tenue de t a t+1.
Pas de look-ahead: teste par troncature (tests/test_prop.py).
Limites [HYPOTHESE]: pas de swaps, pas de gaps intra-jour, couts forfaitaires.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class StratParams:
    lookbacks: tuple[int, ...] = (20, 60, 120)
    target_vol_annual: float = 0.10
    ewma_lambda: float = 0.94
    max_gross: float = 4.0
    cost_bps: float = 1.0        # par unite de notionnel echange [HYPOTHESE]


def _sign(x: float) -> float:
    return (x > 0) - (x < 0)


def weights_series(prices: dict[str, list[float]], p: StratParams) -> list[dict[str, float]]:
    """Poids cibles w[t] (decides a la cloture t) pour chaque t."""
    syms = sorted(prices)
    n = len(prices[syms[0]])
    var = {s: None for s in syms}
    per_asset_vol = p.target_vol_annual / math.sqrt(252) / math.sqrt(len(syms))
    out = []
    for t in range(n):
        w = {}
        for s in syms:
            px = prices[s]
            if t >= 1:
                r = px[t] / px[t - 1] - 1
                var[s] = r * r if var[s] is None else p.ewma_lambda * var[s] + (1 - p.ewma_lambda) * r * r
            if t < max(p.lookbacks) or not var[s]:
                w[s] = 0.0
                continue
            sig = sum(_sign(px[t] / px[t - L] - 1) for L in p.lookbacks) / len(p.lookbacks)
            w[s] = sig * per_asset_vol / math.sqrt(var[s])
        gross = sum(abs(v) for v in w.values())
        if gross > p.max_gross:
            w = {s: v * p.max_gross / gross for s, v in w.items()}
        out.append(w)
    return out


def backtest(prices: dict[str, list[float]], p: StratParams) -> list[float]:
    """Rendements journaliers bruts (sans gouverneur) du portefeuille, jour t+1 pour t>=0."""
    syms = sorted(prices)
    W = weights_series(prices, p)
    rets, prev = [], {s: 0.0 for s in syms}
    for t in range(len(W) - 1):
        gross = sum(W[t][s] * (prices[s][t + 1] / prices[s][t] - 1) for s in syms)
        turn = sum(abs(W[t][s] - prev[s]) for s in syms)
        rets.append(gross - turn * p.cost_bps * 1e-4)
        prev = W[t]
    return rets
