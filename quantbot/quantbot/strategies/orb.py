"""#9 Opening Range Breakout 15 min (ouverture cash New York 09:30) — règles FIGÉES.

Range = barre M15 qui commence à 09:30 NY. Cassure : une clôture au-delà d'un bord avec volume (ticks) >= vol_mult x moyenne des
`vol_n` barres précédentes. Entrée : PULLBACK de confirmation (barre qui re-teste le bord cassé sans clôturer de l'autre côté),
à la clôture, avant `end_hour` NY. Stop = bord opposé du range ; cible = rr x risque (par défaut du moteur). Un trade par jour.
Une clôture au-delà du bord opposé avant l'entrée annule la journée.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import Event

PARAMS = {"vol_mult": 1.2, "vol_n": 20, "end_hour": 12}


def events(df: pd.DataFrame, p: dict = PARAMS) -> list[Event]:
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    vol = df["volume"].to_numpy(float)
    ny = df.index.tz_localize("UTC").tz_convert("America/New_York")
    hm, days = ny.hour * 60 + ny.minute, ny.date
    out: list[Event] = []
    cur = None; hi = lo = np.nan; broke = None; done = False
    for i in range(len(df)):
        if days[i] != cur:
            cur, hi, lo, broke, done = days[i], np.nan, np.nan, None, False
        if hm[i] == 9 * 60 + 30:
            hi, lo = h[i], l[i]
            continue
        if done or np.isnan(hi) or hm[i] < 9 * 60 + 45 or hm[i] >= p["end_hour"] * 60:
            continue
        if broke is None:
            avg = vol[max(0, i - p["vol_n"]):i].mean() if i >= 1 else 0.0
            if c[i] > hi and vol[i] >= p["vol_mult"] * avg:
                broke = "up"
            elif c[i] < lo and vol[i] >= p["vol_mult"] * avg:
                broke = "down"
            continue
        if broke == "up":
            if c[i] < lo:
                done = True
            elif l[i] <= hi < c[i]:
                done = True
                out.append(Event(df.index[i], "bullish", lo, None, "orb_long", {"or_hi": hi, "or_lo": lo}))
        else:
            if c[i] > hi:
                done = True
            elif h[i] >= lo > c[i]:
                done = True
                out.append(Event(df.index[i], "bearish", hi, None, "orb_short", {"or_hi": hi, "or_lo": lo}))
    return out
