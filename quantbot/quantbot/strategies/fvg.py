"""#6 FVG mitigation (H1/H4) — règles FIGÉES.

Fair Value Gap sur barres HTF TERMINÉES (3 bougies) : haussier si low[i] > high[i-2] (zone [high[i-2], low[i]]), baissier si
high[i] < low[i-2]. Niveau d'entrée = Consequent Encroachment (50 % de la zone). Une zone est invalidée dès qu'une barre HTF
TERMINÉE clôture au-delà du bord lointain, et expire après `expiry` barres HTF. Signal (à la clôture d'une barre M15) quand
cette barre touche le CE sans clôturer au-delà du bord lointain ; entrée MARCHÉ à l'ouverture suivante (approximation prudente
d'un ordre limite : aucun avantage de fill n'est supposé). Stop = bord lointain -/+ buf x ATR(HTF) ; cible par défaut (rr du moteur).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.mtf import group_keys
from .events import Event

PARAMS = {"buf": 0.25, "expiry": 50, "atr_period": 14}


def events(df: pd.DataFrame, rule: str, p: dict = PARAMS) -> list[Event]:
    h, l, c, o = (df[k].to_numpy(float) for k in ("high", "low", "close", "open"))
    gid = group_keys(df.index, rule)
    out: list[Event] = []
    bars: list[list[float]] = []  # barres HTF terminées [open, high, low, close]
    zones: list[dict] = []
    atr_h = np.nan
    cur_g = gid[0]; go = gh = gl = gc = None

    def complete():
        nonlocal atr_h
        bars.append([go, gh, gl, gc])
        k = len(bars)
        prev_c = bars[-2][3] if k > 1 else gc
        tr = max(gh - gl, abs(gh - prev_c), abs(gl - prev_c))
        atr_h = tr if np.isnan(atr_h) else (atr_h * (p["atr_period"] - 1) + tr) / p["atr_period"]
        zones[:] = [z for z in zones if k - z["born"] <= p["expiry"]]
        for z in list(zones):  # invalidation par clôture HTF au-delà du bord lointain
            if (z["dir"] == "bullish" and gc < z["lo"]) or (z["dir"] == "bearish" and gc > z["hi"]):
                zones.remove(z)
        if k >= 3:
            b0, b2 = bars[-3], bars[-1]
            if b2[2] > b0[1]:
                zones.append({"dir": "bullish", "lo": b0[1], "hi": b2[2], "ce": (b0[1] + b2[2]) / 2, "born": k, "used": False})
            elif b2[1] < b0[2]:
                zones.append({"dir": "bearish", "lo": b2[1], "hi": b0[2], "ce": (b2[1] + b0[2]) / 2, "born": k, "used": False})

    for i in range(len(df)):
        if gid[i] != cur_g:
            complete()                       # le groupe précédent est TERMINÉ dès qu'une barre d'un groupe suivant apparaît
            cur_g = gid[i]; go = None
        if go is None:
            go, gh, gl = o[i], h[i], l[i]
        else:
            gh, gl = max(gh, h[i]), min(gl, l[i])
        gc = c[i]
        if np.isnan(atr_h):
            continue
        for z in reversed(zones):            # zone la plus récente d'abord ; un seul signal par barre
            if z["used"]:
                continue
            if z["dir"] == "bullish" and l[i] <= z["ce"] and c[i] >= z["lo"]:
                z["used"] = True
                out.append(Event(df.index[i], "bullish", z["lo"] - p["buf"] * atr_h, None, f"fvg_long_{rule}", {"ce": z["ce"]}))
                break
            if z["dir"] == "bearish" and h[i] >= z["ce"] and c[i] <= z["hi"]:
                z["used"] = True
                out.append(Event(df.index[i], "bearish", z["hi"] + p["buf"] * atr_h, None, f"fvg_short_{rule}", {"ce": z["ce"]}))
                break
    return out
