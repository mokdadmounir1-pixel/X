"""Prime « overnight » (stratégie n°16) : achat de l'indice à la clôture du marché cash de New York (16:00 NY), conservé jusqu'à l'ouverture suivante (maintien ~17 h, fixé par `max_hold_bars` de la spec).

Constat de la littérature : sur les indices actions, une grande part du rendement a historiquement été réalisée la nuit. C'est surtout du BÊTA HAUSSIER de l'indice (aucune neutralité) : le comparateur obligatoire reste l'achat-conservation.
Signal à la clôture de la barre M15 qui commence à 15:45 NY, lundi à jeudi (jamais le vendredi : pas de week-end). Stop `stop_atr` x ATR(M15) (large : le risque d'une nuit n'est pas celui d'une barre) ; cible très éloignée : la sortie normale est TEMPORELLE.
Un seul sens (acheteur). Aucune donnée externe ; causal (ATR sur les barres passées).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import Event, atr_series

PARAMS = {"stop_atr": 12.0, "target_atr": 40.0, "close_minute": 15 * 60 + 45, "days": [0, 1, 2, 3]}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}
    ny = df.index.tz_localize("UTC").tz_convert("America/New_York"); hm = ny.hour * 60 + ny.minute; dow = ny.dayofweek
    c = df["close"].to_numpy(float); atr = atr_series(df, 14); out = []
    for i in range(len(df)):
        if hm[i] != p["close_minute"] or dow[i] not in p["days"] or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        out.append(Event(df.index[i], "bullish", c[i] - p["stop_atr"] * atr[i], c[i] + p["target_atr"] * atr[i], "overnight_premium", {"atr": float(atr[i])}))
    return out
