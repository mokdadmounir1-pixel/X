"""#5 VWAP à bandes — retour à la moyenne ; règles FIGÉES.

VWAP de la journée de marché NY (roll 17:00) pondéré par le volume en TICKS (le volume réel n'existe pas sur ces CFD).
Écart-type pondéré du prix typique autour du VWAP. Entrée à la clôture si |z| >= k (>= min_bars barres dans la session) :
  short si z >= k, long si z <= -k ; stop = VWAP +/- stop_k x sigma ; cible = VWAP (RR exigé >= min_rr). Une fois par côté et par session.
Limite : « sans catalyseur fondamental » n'est pas modélisable ici (pas de calendrier économique dans les données).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.mtf import group_keys
from .events import Event

PARAMS = {"k": 2.5, "stop_k": 3.5, "min_bars": 16, "min_rr": 1.5}


def events(df: pd.DataFrame, p: dict = PARAMS) -> list[Event]:
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    w = df["volume"].to_numpy(float)
    gid = group_keys(df.index, "1D")
    tp = (h + l + c) / 3.0
    out: list[Event] = []
    cur = -1
    sw = swp = swp2 = 0.0; n = 0; fired = set()
    for i in range(len(df)):
        if gid[i] != cur:
            cur, sw, swp, swp2, n, fired = gid[i], 0.0, 0.0, 0.0, 0, set()
        if w[i] <= 0:
            continue
        sw += w[i]; swp += w[i] * tp[i]; swp2 += w[i] * tp[i] ** 2; n += 1
        if n < p["min_bars"]:
            continue
        vwap = swp / sw
        sd = np.sqrt(max(swp2 / sw - vwap ** 2, 0.0))
        if sd <= 0:
            continue
        z = (c[i] - vwap) / sd
        if z >= p["k"] and "s" not in fired:
            fired.add("s"); stop = vwap + p["stop_k"] * sd
            if stop > c[i] and (c[i] - vwap) / (stop - c[i]) >= p["min_rr"]:
                out.append(Event(df.index[i], "bearish", stop, vwap, "vwap_short", {"z": float(z)}))
        elif z <= -p["k"] and "l" not in fired:
            fired.add("l"); stop = vwap - p["stop_k"] * sd
            if stop < c[i] and (vwap - c[i]) / (c[i] - stop) >= p["min_rr"]:
                out.append(Event(df.index[i], "bullish", stop, vwap, "vwap_long", {"z": float(z)}))
    return out
