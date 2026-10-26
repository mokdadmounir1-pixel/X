"""Topologie des stops : réservoirs de liquidité (plus hauts/bas égaux), balayage, puis validation de retour (reclaim) — entrée APRÈS la purge.

Réservoir = amas de sommets (ou creux) à moins de `tol_atr` ATR les uns des autres parmi les `lookback` dernières barres ; score de réservoir continu dans [0, 1]
(nombre de touches, serrage). Balayage = dépassement du niveau par une mèche d'au moins `sweep_min_atr`. Retour = clôture revenue dans le range. Score final = produit continu.
Limite : les « pools de stops des particuliers » ne sont pas observables ; seul un proxy structurel (égalités de niveaux) l'est.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import Event, atr_series

PARAMS = {"lookback": 48, "tol_atr": 0.25, "min_touches": 2, "touch_full": 4, "sweep_min_atr": 0.1, "sweep_full_atr": 0.6, "reclaim_full": 0.5, "s_min": 0.5,
          "stop_atr": 1.8, "rr": 3.0, "cooldown": 8, "session": [7, 17]}


def _ramp(x, lo, hi):
    return float(np.clip((x - lo) / (hi - lo), 0.0, 1.0))


def pool_score(levels: np.ndarray, atr: float, p: dict) -> tuple[float, float]:
    """(score de réservoir [0,1], niveau du réservoir). Amas = plus grand groupe de niveaux dans une bande de `tol_atr` ATR."""
    if len(levels) == 0 or atr <= 0:
        return 0.0, float("nan")
    lv = np.sort(levels); band = p["tol_atr"] * atr; best_n, best_lvl, j = 0, float("nan"), 0
    for i in range(len(lv)):
        while lv[i] - lv[j] > band:
            j += 1
        if i - j + 1 > best_n:
            best_n, best_lvl = i - j + 1, float(lv[j:i + 1].mean())
    if best_n < p["min_touches"]:
        return 0.0, best_lvl
    return _ramp(best_n, p["min_touches"] - 1, p["touch_full"]), best_lvl


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close")); atr = atr_series(df, 14)
    sess = (df.index.hour >= p["session"][0]) & (df.index.hour < p["session"][1]); out, last = [], -10**9; lb = p["lookback"]
    for i in range(lb + 14, len(df)):
        if not sess[i] or not np.isfinite(atr[i]) or i - last < p["cooldown"]:
            continue
        a = atr[i]; win = slice(i - lb, i - 1)
        ph, lvl_h = pool_score(h[win], a, p); pl, lvl_l = pool_score(l[win], a, p)
        # balayage au-dessus d'un réservoir de sommets, puis clôture revenue sous le niveau -> vente
        sweep_up = _ramp((h[i] - lvl_h) / a, p["sweep_min_atr"], p["sweep_full_atr"]) if np.isfinite(lvl_h) else 0.0
        reclaim_dn = _ramp((lvl_h - c[i]) / a, 0.0, p["reclaim_full"]) if np.isfinite(lvl_h) else 0.0
        sweep_dn = _ramp((lvl_l - l[i]) / a, p["sweep_min_atr"], p["sweep_full_atr"]) if np.isfinite(lvl_l) else 0.0
        reclaim_up = _ramp((c[i] - lvl_l) / a, 0.0, p["reclaim_full"]) if np.isfinite(lvl_l) else 0.0
        s_short = (ph * sweep_up * reclaim_dn) ** (1 / 3); s_long = (pl * sweep_dn * reclaim_up) ** (1 / 3)
        if s_short >= p["s_min"] and s_short >= s_long:
            stop = c[i] + p["stop_atr"] * a; out.append(Event(df.index[i], "bearish", stop, c[i] - p["rr"] * (stop - c[i]), "hunt_short", {"confidence": min(s_short, 1.0), "S": s_short, "pool": ph})); last = i
        elif s_long >= p["s_min"]:
            stop = c[i] - p["stop_atr"] * a; out.append(Event(df.index[i], "bullish", stop, c[i] + p["rr"] * (c[i] - stop), "hunt_long", {"confidence": min(s_long, 1.0), "S": s_long, "pool": pl})); last = i
    return out
