"""Séances cash (New York) reconstruites CAUSALEMENT depuis des barres M15 : outils communs des stratégies « indices / actions » (gap, IBS, RSI(2), fin de mois, ORB à volume inhabituel).

Une séance = les barres qui commencent entre 09:30 et 15:45 NY (heure locale New York, DST géré). Toutes les statistiques d'une séance ne sont connues qu'après sa DERNIÈRE barre ; les stratégies n'utilisent que des séances terminées avant la barre courante.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

OPEN_MIN, LAST_MIN = 9 * 60 + 30, 15 * 60 + 45


def ny_minutes(df: pd.DataFrame, tz: str = "America/New_York"):
    ny = df.index.tz_localize("UTC").tz_convert(tz)
    return ny.hour * 60 + ny.minute, ny.dayofweek, ny.normalize()


def cash_sessions(df: pd.DataFrame, tz: str = "America/New_York", open_min: int = OPEN_MIN, last_min: int = LAST_MIN) -> list[dict]:
    """Liste ordonnée de séances : {day, first, last, open, high, low, close, first_vol, complete}. `complete` = la barre 15:45 est présente (séance finie)."""
    hm, _, day = ny_minutes(df, tz)
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close")); v = df["volume"].to_numpy(float) if "volume" in df else np.zeros(len(df))
    out: list[dict] = []; cur = None
    for i in range(len(df)):
        if not (open_min <= hm[i] <= last_min):
            continue
        if cur is None or cur["day"] != day[i]:
            cur = {"day": day[i], "first": i, "last": i, "open": o[i], "high": h[i], "low": l[i], "close": c[i], "first_vol": v[i] if hm[i] == open_min else float("nan"), "complete": False}; out.append(cur)
        cur["last"] = i; cur["high"] = max(cur["high"], h[i]); cur["low"] = min(cur["low"], l[i]); cur["close"] = c[i]
        if hm[i] == last_min:
            cur["complete"] = True
    return out


def mean_range(sessions: list[dict], upto: int, n: int = 10) -> float:
    """Amplitude moyenne (haut - bas) des `n` séances COMPLÈTES d'indice < upto ; NaN s'il y en a moins de n/2."""
    r = [s["high"] - s["low"] for s in sessions[:upto] if s["complete"]][-n:]
    return float(np.mean(r)) if len(r) >= max(3, n // 2) else float("nan")
