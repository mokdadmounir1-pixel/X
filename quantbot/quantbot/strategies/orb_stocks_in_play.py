"""ORB sur « actions en jeu » (candidat tiré de Zarattini, Barbon, Aziz) : cassure de la première barre de la séance, uniquement quand le volume d'ouverture est inhabituel.

Adaptation DÉCLARÉE à nos données : barres M15 (pas de barre de 5 minutes), volume = ticks du courtier (pas des actions échangées), et un SEUIL absolu de volume relatif (`rvol_min`) à la place du classement des 20 meilleurs d'un univers de 500 actions.
RVOL = volume de la barre 09:30 / moyenne des mêmes barres des 14 séances précédentes (`equity_formulas.rvol`). Filtres : ouverture > `min_price`, ATR(14 séances) > `min_atr`. Barre 09:30 haussière -> achat à sa clôture ; baissière -> vente.
Stop = `stop_frac` x ATR(14 séances) (10 % dans l'article : très serré) ; sortie temporelle à 16:00 NY (maintien fixé par la spec). Si la colonne `spread` existe : entrée refusée quand le coût estimé dépasse `max_cost_r` en unités de risque (`cost_in_r`).
Sans actions chez le courtier : aucun événement. Le résultat publié (Sharpe 2,81) n'est pas reproduit ici.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..stat.equity_formulas import cost_in_r, orb_stop_distance, rvol
from .events import Event
from .sessions import cash_sessions

PARAMS = {"rvol_min": 2.0, "min_price": 5.0, "min_atr": 0.5, "stop_frac": 0.10, "target_atr": 5.0, "max_cost_r": 0.3}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; ss = cash_sessions(df); o, c = df["open"].to_numpy(float), df["close"].to_numpy(float)
    sp = df["spread"].to_numpy(float) if "spread" in df else None; out = []
    for k in range(15, len(ss)):
        s = ss[k]; i = s["first"]
        if (s["last"] < i) or not np.isfinite(s["first_vol"]):
            continue
        hist = [x for x in ss[:k] if x["complete"]][-14:]
        if len(hist) < 14:
            continue
        atr = float(np.mean([x["high"] - x["low"] for x in hist])); r = rvol(s["first_vol"], [x["first_vol"] for x in hist])
        if not np.isfinite(r) or r < p["rvol_min"] or o[i] <= p["min_price"] or atr <= p["min_atr"] or c[i] == o[i]:
            continue
        d = 1 if c[i] > o[i] else -1; dist = orb_stop_distance(atr, p["stop_frac"])
        if sp is not None and np.isfinite(sp[i]) and cost_in_r(2.0 * sp[i], dist) > p["max_cost_r"]:
            continue
        out.append(Event(df.index[i], "bullish" if d > 0 else "bearish", float(c[i] - d * dist), float(c[i] + d * p["target_atr"] * atr), "orb_stocks_in_play", {"rvol": float(r), "confidence": min(0.95, 0.55 + 0.1 * (r - p["rvol_min"]))}))
    return out
