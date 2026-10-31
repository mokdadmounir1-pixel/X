"""IBS — Internal Bar Strength (stratégie candidate B) : réversion après une séance qui clôture près de son plus bas (ou haut) sur les indices.

IBS = (clôture - bas) / (haut - bas) de la séance cash complète (09:30-16:00 NY). IBS <= `ibs_low` -> achat à la clôture de la barre 15:45 ; IBS >= `ibs_high` -> vente. Stop `stop_a` x A (A = amplitude moyenne des 10 dernières séances),
cible `target_a` x A ; sortie temporelle (maintien court, fixé par la spec). Confiance continue : rampe sur l'extrémité de l'IBS. Mesure intuitive, publiée par des praticiens ; AUCUNE valeur démontrée ici. Causal : séance terminée.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .apex import ramp
from .events import Event
from .sessions import cash_sessions, mean_range

PARAMS = {"ibs_low": 0.2, "ibs_high": 0.8, "stop_a": 2.0, "target_a": 1.0, "both_sides": True}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; ss = cash_sessions(df); c = df["close"].to_numpy(float); out = []
    for k, s in enumerate(ss):
        if not s["complete"] or s["high"] <= s["low"]:
            continue
        A = mean_range(ss, k + 1)
        if not np.isfinite(A) or A <= 0:
            continue
        ibs = (s["close"] - s["low"]) / (s["high"] - s["low"]); px = c[s["last"]]
        if ibs <= p["ibs_low"]:
            d, ext = 1, (p["ibs_low"] - ibs) / max(p["ibs_low"], 1e-9)
        elif ibs >= p["ibs_high"] and p["both_sides"]:
            d, ext = -1, (ibs - p["ibs_high"]) / max(1 - p["ibs_high"], 1e-9)
        else:
            continue
        conf = min(0.95, 0.55 + 0.4 * float(ramp(ext, 0.0, 1.0)))
        out.append(Event(df.index[s["last"]], "bullish" if d > 0 else "bearish", px - d * p["stop_a"] * A, px + d * p["target_a"] * A, "ibs_reversion", {"ibs": float(ibs), "confidence": conf}))
    return out
