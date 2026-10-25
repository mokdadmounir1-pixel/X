"""Structure de marché : pivots confirmés, niveaux S/R, tendance HH/HL."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


@dataclass(frozen=True)
class Pivot:
    idx: int
    price: float
    kind: str  # "H" (sommet) ou "L" (creux)


def swing_points(high: np.ndarray, low: np.ndarray, order: int) -> list[Pivot]:
    """Pivots confirmés (`order` barres de chaque côté), alternés H/L.

    Un pivot en position i n'est connu qu'à i+order : aucun look-ahead tant
    qu'on appelle la fonction sur les données disponibles à l'instant t.
    """
    n = len(high)
    width = 2 * order + 1
    if n < width:
        return []
    h_win = sliding_window_view(high, width)
    l_win = sliding_window_view(low, width)
    centers = np.arange(order, n - order)
    raw = [Pivot(int(i), float(high[i]), "H") for i in centers[h_win.argmax(axis=1) == order]]
    raw += [Pivot(int(i), float(low[i]), "L") for i in centers[l_win.argmin(axis=1) == order]]
    raw.sort(key=lambda p: (p.idx, p.kind))
    merged: list[Pivot] = []
    for p in raw:
        if merged and merged[-1].kind == p.kind:
            better = p.price > merged[-1].price if p.kind == "H" else p.price < merged[-1].price
            if better:
                merged[-1] = p
        else:
            merged.append(p)
    return merged


def find_levels(pivots: list[Pivot], tolerance: float = 0.005) -> list[tuple[float, int]]:
    """Regroupe les pivots proches (écart relatif <= tolerance) en niveaux S/R.

    Retourne [(prix_moyen, nb_touches)] trié par nb_touches décroissant.
    """
    clusters: list[list[float]] = []
    for price in sorted(p.price for p in pivots):
        if clusters and abs(price - np.mean(clusters[-1])) / np.mean(clusters[-1]) <= tolerance:
            clusters[-1].append(price)
        else:
            clusters.append([price])
    levels = [(float(np.mean(c)), len(c)) for c in clusters]
    return sorted(levels, key=lambda x: -x[1])


def market_structure(pivots: list[Pivot]) -> str:
    """'up' (HH+HL), 'down' (LH+LL) ou 'range' d'après les deux derniers H et L."""
    highs = [p.price for p in pivots if p.kind == "H"][-2:]
    lows = [p.price for p in pivots if p.kind == "L"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return "range"
    if highs[1] > highs[0] and lows[1] > lows[0]:
        return "up"
    if highs[1] < highs[0] and lows[1] < lows[0]:
        return "down"
    return "range"
