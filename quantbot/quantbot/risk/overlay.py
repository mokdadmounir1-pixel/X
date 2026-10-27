"""Surcouche de risque CONTINUE (jamais un oui/non) : multiplicateur de taille dans [0, 1] qui ne peut QUE réduire le risque.

  news_factor : 0 pile sur une publication macro, remonte linéairement à 1 à `window_min` minutes avant/après (abstention douce autour des annonces) ;
  tail_factor : 1 tant que la queue de pertes récente (ES 99 % sur `recent` rendements) ne dépasse pas `ratio_lo` fois la queue de référence (`ref` rendements) ; décroît jusqu'à `floor` à `ratio_hi`.
Le produit est le multiplicateur final. Désactivé par défaut dans les specs (identités d'essais inchangées) ; activé dans le direct PAPER via `build_overlay`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..data.external import load_events
from .var import historical_var_es


def news_factor(ts: pd.Timestamp, events: pd.DataFrame, window_min: float = 15.0) -> float:
    if events is None or events.empty:
        return 1.0
    dt = np.abs((events["time"] - ts).dt.total_seconds().to_numpy()) / 60.0
    return float(np.clip(dt.min() / window_min, 0.0, 1.0))


def tail_factor(returns: np.ndarray, recent: int = 500, ref: int = 5000, ratio_lo: float = 1.2, ratio_hi: float = 2.0, floor: float = 0.25) -> float:
    r = np.asarray(returns, float); r = r[np.isfinite(r)]
    if len(r) < recent + 200:
        return 1.0                                           # pas assez d'historique : on ne réduit pas sur du vide
    es_recent = historical_var_es(r[-recent:], 0.99)["es"]; es_ref = historical_var_es(r[-ref:], 0.99)["es"]
    if not (np.isfinite(es_recent) and np.isfinite(es_ref)) or es_ref <= 0:
        return 1.0
    ratio = es_recent / es_ref
    return float(np.clip(1.0 - (1.0 - floor) * (ratio - ratio_lo) / (ratio_hi - ratio_lo), floor, 1.0))


class Overlay:
    def __init__(self, events: Optional[pd.DataFrame] = None, window_min: float = 15.0) -> None:
        self.events, self.window_min = events, window_min

    def multiplier(self, ts: pd.Timestamp, close: Optional[pd.Series] = None) -> dict:
        n = news_factor(ts, self.events, self.window_min) if self.events is not None else 1.0
        t = tail_factor(np.log(close).diff().to_numpy()) if close is not None else 1.0
        return {"news": n, "tail": t, "multiplier": float(n * t)}


def build_overlay(root: Path, now: Optional[pd.Timestamp] = None, window_min: float = 15.0) -> Overlay:
    now = now or pd.Timestamp.utcnow().tz_localize(None)
    return Overlay(load_events(root, now - pd.Timedelta(days=30), now + pd.Timedelta(days=400)), window_min)
