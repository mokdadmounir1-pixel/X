"""Caractéristiques causales d'un setup SMC à l'entrée et filtres PRÉDÉCLARÉS (six, binaires) : sert à comparer les trades gagnants ET perdants, jamais les gagnants seuls.

Chaque caractéristique n'utilise que des données <= l'instant du signal. Les filtres n'ont qu'un seuil, fixé sur la première moitié chronologique des données de recherche (jamais sur la seconde).
Filtres : trend_aligned (tendance D1 alignée), session (07-20 UTC), stop_wide (distance du stop >= seuil en ATR M15), stop_narrow (<= seuil), vol_high (ATR M15 / médiane 500 barres >= seuil), ob_big (hauteur de l'OB >= seuil en ATR M15).
« Achats seulement » n'est volontairement PAS proposé : sur l'or et l'USTEC ce serait du bêta haussier.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.mtf import htf_state
from .events import Event, atr_series

FILTERS = ("trend_aligned", "session", "stop_wide", "stop_narrow", "vol_high", "ob_big")


def features(df: pd.DataFrame, events: list[Event]) -> list[dict]:
    atr = atr_series(df, 14); med = pd.Series(atr).rolling(500, min_periods=100).median().to_numpy(); d1 = htf_state(df, "1D").to_numpy(); out = []
    for e in events:
        i = df.index.get_loc(e.ts); px = float(df["close"].iloc[i]); a = atr[i]; ob = e.meta.get("ob", (np.nan, np.nan)); sgn = 1 if e.direction == "bullish" else -1
        out.append({"i": i, "dir": sgn, "hour": int(e.ts.hour), "trend_aligned": float(d1[i] == sgn), "stop_atr": abs(px - e.stop) / a if a > 0 else np.nan,
                    "vol_rel": float(a / med[i]) if np.isfinite(med[i]) and med[i] > 0 else np.nan, "ob_atr": abs(ob[1] - ob[0]) / a if a > 0 else np.nan, "rr": float(e.meta.get("rr", np.nan))})
    return out


def keep_mask(feats: list[dict], spec: dict | None) -> np.ndarray:
    """Masque booléen des événements conservés par le filtre `spec` = {"name": ..., "threshold": ...} ; None = tout garder."""
    if not spec:
        return np.ones(len(feats), bool)
    n, t = spec["name"], spec.get("threshold")
    if n == "trend_aligned":
        return np.array([f["trend_aligned"] == 1.0 for f in feats])
    if n == "session":
        return np.array([7 <= f["hour"] < 20 for f in feats])
    if n == "stop_wide":
        return np.array([np.isfinite(f["stop_atr"]) and f["stop_atr"] >= t for f in feats])
    if n == "stop_narrow":
        return np.array([np.isfinite(f["stop_atr"]) and f["stop_atr"] <= t for f in feats])
    if n == "vol_high":
        return np.array([np.isfinite(f["vol_rel"]) and f["vol_rel"] >= t for f in feats])
    if n == "ob_big":
        return np.array([np.isfinite(f["ob_atr"]) and f["ob_atr"] >= t for f in feats])
    raise ValueError(f"filtre inconnu : {n}")


def apply(df: pd.DataFrame, events: list[Event], spec: dict | None) -> list[Event]:
    if not spec or not events:
        return events
    m = keep_mask(features(df, events), spec)
    return [e for e, k in zip(events, m) if k]
