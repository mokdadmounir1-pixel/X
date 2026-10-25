"""#1 AMD / Power of 3 — règles mécaniques FIGÉES (la description d'origine est qualitative).

Accumulation : range de la session asiatique (barres commençant entre 00:00 et 07:00 UTC, >= 20 barres M15).
Manipulation : entre 07:00 et 10:00 UTC, le prix dépasse un bord du range d'au moins `buf` x ATR (sweep).
Distribution : dès qu'une clôture réintègre le range, entrée à la clôture dans le sens OPPOSÉ au sweep ;
  stop = extrême du sweep +/- `stop_buf` x ATR ; cible = bord opposé du range (exigé : RR >= min_rr).
Une tentative par jour. 'jour' = date UTC.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import Event, atr_series

PARAMS = {"asia": (0, 7), "manip": (7, 10), "buf": 0.1, "stop_buf": 0.1, "min_rr": 1.5, "min_asia_bars": 20}


def events(df: pd.DataFrame, p: dict = PARAMS) -> list[Event]:
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = atr_series(df)
    hours, days = df.index.hour.to_numpy(), df.index.normalize()
    out: list[Event] = []
    cur = None
    hi = lo = np.nan
    nb = 0; sweep = None; ext = np.nan; done = False
    for i in range(len(df)):
        if days[i] != cur:
            cur, hi, lo, nb, sweep, ext, done = days[i], np.nan, np.nan, 0, None, np.nan, False
        hr = hours[i]
        if p["asia"][0] <= hr < p["asia"][1]:
            hi = h[i] if np.isnan(hi) else max(hi, h[i])
            lo = l[i] if np.isnan(lo) else min(lo, l[i])
            nb += 1
        elif p["manip"][0] <= hr < p["manip"][1] and nb >= p["min_asia_bars"] and not done and np.isfinite(atr[i]):
            a = atr[i]
            if sweep is None:
                if h[i] > hi + p["buf"] * a:
                    sweep, ext = "up", h[i]
                elif l[i] < lo - p["buf"] * a:
                    sweep, ext = "down", l[i]
            elif sweep == "up":
                ext = max(ext, h[i])
            else:
                ext = min(ext, l[i])
            if sweep == "up" and c[i] < hi:
                stop, target = ext + p["stop_buf"] * a, lo
                done = True
                if stop > c[i] and (c[i] - target) / (stop - c[i]) >= p["min_rr"]:
                    out.append(Event(df.index[i], "bearish", stop, target, "amd_short", {"asia_hi": hi, "asia_lo": lo}))
            elif sweep == "down" and c[i] > lo:
                stop, target = ext - p["stop_buf"] * a, hi
                done = True
                if stop < c[i] and (target - c[i]) / (c[i] - stop) >= p["min_rr"]:
                    out.append(Event(df.index[i], "bullish", stop, target, "amd_long", {"asia_hi": hi, "asia_lo": lo}))
    return out
