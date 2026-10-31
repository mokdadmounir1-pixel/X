"""Gap d'ouverture (stratégie candidate A) : retour vers la clôture de la veille après un écart d'ouverture MODÉRÉ sur les indices.

Écart = ouverture 09:30 NY - clôture de la dernière barre (15:45) de la séance précédente. Condition : g_min x A <= |écart| <= g_max x A où A = amplitude moyenne des 10 dernières séances (un grand écart vient d'une nouvelle : on ne le combat pas).
Entrée à la clôture de la première barre M15 (09:45) dans le sens OPPOSÉ à l'écart ; cible = clôture de la veille ; stop = `stop_a` x A au-delà de l'ouverture ; rapport gain/risque >= `min_rr`. Une tentative par séance. Confiance continue : rampe sur |écart|/A.
Hypothèse (à tester, non prouvée) : les écarts modérés des indices se comblent plus souvent qu'ils ne se prolongent. Causal : la barre 09:30 est terminée à l'entrée.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .apex import ramp
from .events import Event
from .sessions import cash_sessions, mean_range

PARAMS = {"g_min": 0.25, "g_max": 1.5, "stop_a": 0.6, "min_rr": 0.8}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; ss = cash_sessions(df); c = df["close"].to_numpy(float); out = []
    for k in range(1, len(ss)):
        s, prev = ss[k], ss[k - 1]; i = s["first"] + 1
        if not prev["complete"] or i > s["last"] or i >= len(df) or (df.index[i] - df.index[s["first"]]) != pd.Timedelta(minutes=15):
            continue
        A = mean_range(ss, k)
        if not np.isfinite(A) or A <= 0:
            continue
        gap = s["open"] - prev["close"]; size = abs(gap) / A
        if size < p["g_min"] or size > p["g_max"]:
            continue
        d = -1 if gap > 0 else 1; px = c[i]
        stop = (s["open"] + p["stop_a"] * A) if gap > 0 else (s["open"] - p["stop_a"] * A)
        tgt = prev["close"]; risk, rew = abs(px - stop), abs(tgt - px)
        if (gap > 0 and not (tgt < px < stop)) or (gap < 0 and not (stop < px < tgt)) or risk <= 0 or rew < p["min_rr"] * risk:
            continue
        conf = min(0.95, 0.55 + 0.4 * float(ramp(size, p["g_min"], 1.0)))
        out.append(Event(df.index[i], "bearish" if gap > 0 else "bullish", float(stop), float(tgt), "gap_fade", {"gap_a": float(gap / A), "confidence": conf}))
    return out
