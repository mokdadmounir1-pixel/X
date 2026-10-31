"""RSI(2) sur séances (stratégie candidate C) : réversion de très court terme avec filtre de tendance COURT (adaptation déclarée de la règle classique à 200 jours : le flux direct ne contient qu'environ un mois de barres M15).

RSI de période 2 (Wilder) sur les clôtures des séances cash complètes. Achat à la clôture 15:45 NY si RSI(2) <= `rsi_low` ET clôture > moyenne des `trend_days` dernières clôtures de séance ; vente symétrique (RSI(2) >= `rsi_high` ET clôture < moyenne). Stop `stop_a` x A, cible `target_a` x A (A = amplitude moyenne 10 séances) ; sortie temporelle.
Confiance continue : rampe sur l'extrémité du RSI. Causal. Aucune valeur démontrée ; le filtre court n'est PAS celui de la littérature (200 jours) : nommé comme tel.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .apex import ramp
from .events import Event
from .sessions import cash_sessions, mean_range

PARAMS = {"rsi_low": 20.0, "rsi_high": 80.0, "trend_days": 10, "stop_a": 2.0, "target_a": 1.0}


def rsi2(closes: np.ndarray, period: int = 2) -> np.ndarray:
    out = np.full(len(closes), np.nan)
    if len(closes) <= period:
        return out
    d = np.diff(closes); up, dn = np.maximum(d, 0.0), np.maximum(-d, 0.0)
    au, ad = up[:period].mean(), dn[:period].mean()
    out[period] = 100.0 if ad == 0 else 100.0 - 100.0 / (1 + au / ad)
    for i in range(period, len(d)):
        au = (au * (period - 1) + up[i]) / period; ad = (ad * (period - 1) + dn[i]) / period
        out[i + 1] = 100.0 if ad == 0 else 100.0 - 100.0 / (1 + au / ad)
    return out


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; ss = cash_sessions(df); idx = [k for k, s in enumerate(ss) if s["complete"]]
    closes = np.array([ss[k]["close"] for k in idx]); r = rsi2(closes); c = df["close"].to_numpy(float); out = []
    for j, k in enumerate(idx):
        if j < p["trend_days"] or not np.isfinite(r[j]):
            continue
        A = mean_range(ss, k + 1)
        if not np.isfinite(A) or A <= 0:
            continue
        ma = closes[j - p["trend_days"]:j].mean(); px = c[ss[k]["last"]]
        if r[j] <= p["rsi_low"] and closes[j] > ma:
            d, ext = 1, (p["rsi_low"] - r[j]) / max(p["rsi_low"], 1e-9)
        elif r[j] >= p["rsi_high"] and closes[j] < ma:
            d, ext = -1, (r[j] - p["rsi_high"]) / max(100 - p["rsi_high"], 1e-9)
        else:
            continue
        conf = min(0.95, 0.55 + 0.4 * float(ramp(ext, 0.0, 1.0)))
        out.append(Event(df.index[ss[k]["last"]], "bullish" if d > 0 else "bearish", px - d * p["stop_a"] * A, px + d * p["target_a"] * A, "rsi2_reversion", {"rsi2": float(r[j]), "confidence": conf}))
    return out
