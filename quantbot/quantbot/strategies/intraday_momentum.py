"""Momentum intrajournalier (stratégie n°14) : le rendement de la première partie de la séance prédit-il la dernière demi-heure ? (Gao, Han, Li, Zhou : « Market intraday momentum »)

Rendement r = clôture de la barre M15 commençant à 09:45 NY (soit 10:00) - clôture de la barre commençant à 15:45 NY de la veille ouvrée. z = r / (ATR(M15) x racine du nombre de barres écoulées).
Si |z| >= `z_entry` : entrée dans le SENS de r à la clôture de la barre qui commence à 15:15 NY (soit 15:30), sortie par le temps (`max_hold_bars` ~ 3-4 barres) ou stop `stop_atr` x ATR / cible `target_atr` x ATR.
Confiance continue : rampe de |z| entre `z_entry` et `z_full`. Causal : seul le passé est lu.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .apex import ramp
from .events import Event, atr_series

PARAMS = {"z_entry": 1.0, "z_full": 3.0, "stop_atr": 1.5, "target_atr": 3.0, "first_minute": 9 * 60 + 45, "prev_close_minute": 15 * 60 + 45, "entry_minute": 15 * 60 + 15}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}
    ny = df.index.tz_localize("UTC").tz_convert("America/New_York"); hm = ny.hour * 60 + ny.minute; day = ny.normalize()
    c = df["close"].to_numpy(float); atr = atr_series(df, 14); out = []
    prev_close = prev_pos = None; first = None; today = None
    for i in range(len(df)):
        if day[i] != today:
            today = day[i]; first = None
        if hm[i] == p["prev_close_minute"]:
            prev_close, prev_pos = c[i], i
        elif hm[i] == p["first_minute"] and prev_close is not None and prev_pos is not None and np.isfinite(atr[i]) and atr[i] > 0:
            n = max(i - prev_pos, 1); first = (c[i] - prev_close) / (atr[i] * np.sqrt(n))
        elif hm[i] == p["entry_minute"] and first is not None and abs(first) >= p["z_entry"] and np.isfinite(atr[i]) and atr[i] > 0:
            s = 1 if first > 0 else -1; conf = min(0.95, 0.55 + 0.4 * float(ramp(abs(first), p["z_entry"], p["z_full"])))
            out.append(Event(df.index[i], "bullish" if s > 0 else "bearish", c[i] - s * p["stop_atr"] * atr[i], c[i] + s * p["target_atr"] * atr[i], "intraday_momentum", {"z": float(first), "confidence": conf}))
            first = None
    return out
