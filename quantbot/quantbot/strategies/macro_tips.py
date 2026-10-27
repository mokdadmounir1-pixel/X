"""Global macro / taux réels (stratégies n°3 et n°7) : l'or contre les taux réels américains à 10 ans (TIPS, série FRED DFII10), signal LENT.

Variation du taux réel sur `change_days` jours, centrée-réduite sur `z_days` jours (causal, publication décalée d'un jour). Taux réels en forte BAISSE (z <= -z_entry) -> achat de l'or ; en forte HAUSSE -> vente.
Une fois par jour à 07h UTC ; stop/cible en ATR JOURNALIER. Sans fichier data/external/fred_DFII10.csv (clé FRED gratuite requise pour le télécharger) : AUCUN événement. Peu de trades par construction.
L'hypothèse (corrélation inverse or / taux réels) est un fait stylisé instable dans le temps : c'est un essai, pas une loi.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .apex import ramp
from .events import Event
from .external_data import load_fred
from .smc import htf_arrays, wilder_atr

PARAMS = {"change_days": 10, "z_days": 250, "z_entry": 1.5, "z_full": 3.0, "stop_atr_d1": 2.0, "rr": 1.5, "hour": 7, "cooldown_days": 5, "root": None}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; ry = load_fred("DFII10", p["root"])
    if ry is None:
        return []
    chg = ry.diff(p["change_days"]); z = (chg - chg.rolling(p["z_days"]).mean()) / chg.rolling(p["z_days"]).std()
    a = htf_arrays(df, "1D"); atr_d = wilder_atr(a["h"], a["l"], a["c"], 14); done = a["done_at"][:-1]; c = df["close"].to_numpy(float)
    out, last_day = [], None
    for day, i in pd.Series(np.arange(len(df)), index=df.index).groupby(df.index.normalize()).first().items():
        if df.index[i].hour > p["hour"] or df.index[i].dayofweek >= 5:
            continue
        zz = z.reindex([day], method="ffill").iloc[0] if day >= z.index[0] else np.nan
        k = np.searchsorted(done, i, side="right") - 1
        if not np.isfinite(zz) or abs(zz) < p["z_entry"] or k < 0 or not np.isfinite(atr_d[k]) or (last_day is not None and (day - last_day).days < p["cooldown_days"]):
            continue
        sg = 1 if zz < 0 else -1; stop = c[i] - sg * p["stop_atr_d1"] * atr_d[k]; tgt = c[i] + sg * p["rr"] * p["stop_atr_d1"] * atr_d[k]
        out.append(Event(df.index[i], "bullish" if sg > 0 else "bearish", stop, tgt, f"macro_{'long' if sg > 0 else 'short'}", {"confidence": float(ramp(abs(zz), p["z_entry"], p["z_full"])), "z": float(zz)})); last_day = day
    return out
