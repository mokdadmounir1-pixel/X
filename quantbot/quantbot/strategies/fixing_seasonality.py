"""Saisonnalité des fixings LBMA (stratégie n°12) : fenêtres de liquidité autour des fixings de Londres (10h30 et 15h00, HEURE DE LONDRES : l'heure UTC varie avec l'heure d'été britannique).

Hypothèse testable, direction FIXÉE à l'avance : MOMENTUM avant le fixing : à `lead_min` minutes avant le fixing, on entre dans le sens du rendement de la dernière heure (si |rendement| >= `min_move_atr` x ATR), sortie à l'heure du fixing
(max_hold) ; stop `stop_atr` x ATR, cible `rr` x risque. Les « effets de fixing » sont documentés pour d'autres périodes ; rien ne dit qu'ils subsistent ou qu'ils soient exploitables après coûts : c'est un essai.
Sur barres M15 la fenêtre est approchée au quart d'heure.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import Event, atr_series

PARAMS = {"fixings_local": ["10:30", "15:00"], "tz": "Europe/London", "lead_min": 60, "lookback_bars": 4, "min_move_atr": 0.5, "stop_atr": 1.2, "rr": 1.5, "cooldown": 8}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; c = df["close"].to_numpy(float); atr = atr_series(df, 14)
    loc = pd.DatetimeIndex(df.index).tz_localize("UTC").tz_convert(p["tz"]); hm = loc.strftime("%H:%M"); out, last = [], -10**9
    targets = {(pd.Timestamp(f"2000-01-01 {f}") - pd.Timedelta(minutes=p["lead_min"])).strftime("%H:%M") for f in p["fixings_local"]}
    for i in range(p["lookback_bars"] + 14, len(df) - 1):
        if hm[i] not in targets or not np.isfinite(atr[i]) or i - last < p["cooldown"] or loc[i].dayofweek >= 5:
            continue
        move = (c[i] - c[i - p["lookback_bars"]]) / atr[i]
        if abs(move) < p["min_move_atr"]:
            continue
        sg = 1 if move > 0 else -1; stop = c[i] - sg * p["stop_atr"] * atr[i]; tgt = c[i] + sg * p["rr"] * p["stop_atr"] * atr[i]
        out.append(Event(df.index[i], "bullish" if sg > 0 else "bearish", stop, tgt, f"fix_{'long' if sg > 0 else 'short'}", {"confidence": min(abs(move) / 2.0, 1.0), "move_atr": float(move)})); last = i
    return out
