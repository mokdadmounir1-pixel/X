"""Effet de changement de mois (stratégie candidate D) : achat de l'indice à la clôture du dernier jour ouvré du mois, conservé quelques séances (maintien fixé par la spec).

Dernier jour ouvré = le prochain jour lundi-vendredi tombe dans un autre mois (les jours fériés boursiers ne sont PAS modélisés : approximation déclarée). Signal à la clôture de la barre 15:45 NY. Acheteur seulement, stop `stop_a` x A, cible très éloignée (sortie temporelle).
Effet documenté sur actions américaines (Lakonishok et Smidt, 1988 ; à vérifier avant de s'y fier) ; ici surtout du BÊTA haussier de l'indice : comparateur = achat-conservation. Une dizaine de signaux par an : très peu de puissance statistique.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import Event
from .sessions import cash_sessions, mean_range

PARAMS = {"stop_a": 3.0, "target_a": 8.0}


def next_weekday(d: pd.Timestamp) -> pd.Timestamp:
    n = d + pd.Timedelta(days=1)
    while n.dayofweek >= 5:
        n += pd.Timedelta(days=1)
    return n


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; ss = cash_sessions(df); c = df["close"].to_numpy(float); out = []
    for k, s in enumerate(ss):
        if not s["complete"] or next_weekday(s["day"]).month == s["day"].month:
            continue
        A = mean_range(ss, k + 1)
        if not np.isfinite(A) or A <= 0:
            continue
        px = c[s["last"]]
        out.append(Event(df.index[s["last"]], "bullish", px - p["stop_a"] * A, px + p["target_a"] * A, "turn_of_month", {}))
    return out
