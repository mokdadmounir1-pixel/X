"""Cassure de Londres (stratégie candidate E) : CONTINUATION après la plage de la session asiatique (FX, or, indices à marché quasi continu).

Plage asiatique = barres commençant entre 00:00 et 07:00 UTC (>= `min_bars` barres). Entre 07:00 et 10:00 UTC, première CLÔTURE au-delà d'un bord d'au moins `buf` x ATR -> entrée dans le sens de la cassure à cette clôture ; stop = bord opposé de la plage
(plage exigée entre `min_range_atr` et `max_range_atr` x ATR) ; cible `rr` x risque. Une tentative par jour. Différent d'AMD (qui joue le retour après un balayage). Heures UTC fixes (le décalage DST de Londres n'est pas modélisé). Aucune valeur démontrée.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import Event, atr_series

PARAMS = {"asia": [0, 7], "window": [7, 10], "buf": 0.1, "min_range_atr": 1.5, "max_range_atr": 8.0, "rr": 2.0, "min_bars": 20}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close")); atr = atr_series(df, 14)
    hr = df.index.hour; day = df.index.normalize(); out = []; cur = None; hi = lo = np.nan; n = 0; done = False
    for i in range(len(df)):
        if day[i] != cur:
            cur, hi, lo, n, done = day[i], np.nan, np.nan, 0, False
        if p["asia"][0] <= hr[i] < p["asia"][1]:
            hi = h[i] if np.isnan(hi) else max(hi, h[i]); lo = l[i] if np.isnan(lo) else min(lo, l[i]); n += 1
            continue
        if done or n < p["min_bars"] or not (p["window"][0] <= hr[i] < p["window"][1]) or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        rng = hi - lo
        if rng < p["min_range_atr"] * atr[i] or rng > p["max_range_atr"] * atr[i]:
            continue
        if c[i] > hi + p["buf"] * atr[i]:
            stop, d = lo, 1
        elif c[i] < lo - p["buf"] * atr[i]:
            stop, d = hi, -1
        else:
            continue
        risk = abs(c[i] - stop)
        if risk <= 0:
            continue
        done = True; out.append(Event(df.index[i], "bullish" if d > 0 else "bearish", float(stop), float(c[i] + d * p["rr"] * risk), "london_breakout", {"range_atr": float(rng / atr[i])}))
    return out
