"""Positionnement COT (stratégie n°9) : extrêmes de la position nette « Managed Money » sur l'or (CFTC), approche CONTRARIENNE fixée à l'avance.

Percentile sur 156 semaines (causal, disponible le vendredi suivant le mardi du rapport). Au premier créneau 07h UTC du jour OUVRÉ suivant la disponibilité : percentile >= 100-`edge` -> vente ; <= `edge` -> achat ;
score = extrémité continue (`data.external.cot_extremity`). Sans fichier data/external/cot_gold.csv (collecté par le terminal) : AUCUN événement. Stop `stop_atr` x ATR, cible `rr` x risque, maintien long (voir spec).
Puissance statistique faible par nature (positionnement hebdomadaire : quelques dizaines d'extrêmes en 13 ans).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.external import cot_extremity
from .events import Event, atr_series
from .external_data import load_cot

PARAMS = {"edge": 10.0, "min_extremity": 0.5, "stop_atr": 6.0, "rr": 2.0, "hour": 7, "root": None}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; cot = load_cot(p["root"])
    if cot is None or "percentile_156w" not in cot.columns:
        return []
    atr = atr_series(df, 14); c = df["close"].to_numpy(float); idx = df.index; out = []
    for avail, row in cot.iterrows():
        pct = row["percentile_156w"]; ext = cot_extremity(pct, lo=p["edge"] / 2)
        if not np.isfinite(pct) or ext < p["min_extremity"]:
            continue
        pos = idx.searchsorted(avail.normalize() + pd.Timedelta(days=1, hours=p["hour"]))
        while pos < len(idx) and idx[pos].dayofweek >= 5:
            pos += 1
        if pos >= len(idx) or not np.isfinite(atr[pos]):
            continue
        sg = -1 if pct >= 50 else 1; stop = c[pos] - sg * p["stop_atr"] * atr[pos]; tgt = c[pos] + sg * p["rr"] * p["stop_atr"] * atr[pos]
        out.append(Event(idx[pos], "bullish" if sg > 0 else "bearish", stop, tgt, f"cot_{'long' if sg > 0 else 'short'}", {"confidence": float(ext), "percentile": float(pct)}))
    return out
