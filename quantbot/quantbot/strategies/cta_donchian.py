"""Suivi de tendance (CTA) : cassure de canal de Donchian sur H4 (barres TERMINÉES) filtrée par la tendance D1 continue.

Signal acheteur : la clôture de la barre H4 qui vient de se terminer dépasse le plus haut des `channel` barres H4 PRÉCÉDENTES ET la tendance D1 haussière (score continu de mtf_confluence) >= `d1_min` ; vendeur : symétrique.
Stop = `stop_atr` x ATR(H4) ; cible = `rr` x risque ; fenêtre d'émission 07h-21h UTC. Le filtre de régime HMM du cahier des charges n'est PAS utilisé (voir docs/REVUE_MODULES_PROPOSES.md) : la tendance D1 en tient lieu.
Causal : un signal n'est émis qu'au début du groupe H4 suivant.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import Event
from .mtf_confluence import htf_trend
from .smc import htf_arrays, wilder_atr

PARAMS = {"channel": 20, "stop_atr": 2.5, "rr": 2.0, "d1_min": 0.3, "cooldown_h4": 6, "hours": [7, 21], "d1_fast": 10, "d1_slow": 30, "d1_k": 1.5}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; a = htf_arrays(df, "4h"); n = len(a["c"]); atr = wilder_atr(a["h"], a["l"], a["c"], 14)
    d1 = htf_trend(df, "1D", p["d1_fast"], p["d1_slow"], p["d1_k"]); hr = df.index.hour; out, last_g = [], -10**9
    hi = pd.Series(a["h"]).shift(1).rolling(p["channel"]).max().to_numpy(); lo = pd.Series(a["l"]).shift(1).rolling(p["channel"]).min().to_numpy()
    for g in range(p["channel"] + 14, n - 1):
        s = int(a["done_at"][g])                                   # indice de base où le groupe H4 g est terminé
        if s < 0 or s >= len(df) or not (p["hours"][0] <= hr[s] < p["hours"][1]) or g - last_g < p["cooldown_h4"] or not np.isfinite(atr[g]):
            continue
        c = a["c"][g]; ts = df.index[s]; px = float(df["close"].iloc[s])            # niveaux ancrés sur la clôture de la barre de signal (l'ordre part à l'ouverture suivante)
        if c > hi[g] and d1["bull"][s] >= p["d1_min"]:
            stop = px - p["stop_atr"] * atr[g]; out.append(Event(ts, "bullish", stop, px + p["rr"] * (px - stop), "cta_long", {"confidence": float(min(d1["bull"][s], 1.0)), "d1": float(d1["bull"][s])})); last_g = g
        elif c < lo[g] and d1["bear"][s] >= p["d1_min"]:
            stop = px + p["stop_atr"] * atr[g]; out.append(Event(ts, "bearish", stop, px - p["rr"] * (stop - px), "cta_short", {"confidence": float(min(d1["bear"][s], 1.0)), "d1": float(d1["bear"][s])})); last_g = g
    return out
