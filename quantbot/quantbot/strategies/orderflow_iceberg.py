"""Flux d'ordres et absorption (stratégie n°8) : CVD par barre + absorption volume/déplacement, puis CONTINUATION dans le sens de la sortie.

Absorption (proxy continu, `order_flow_ofi.absorption_score`) : volume de ticks élevé pour un déplacement faible. Une zone d'absorption est suivie, à la barre de sortie, d'une impulsion (corps/ATR) : on trade DANS le sens de l'impulsion
si le CVD cumulé sur `cvd_bars` barres est du même signe (pas de divergence). Score continu = produit de (absorption précédente, impulsion, alignement CVD). Stop = au-delà de l'autre extrémité de la zone, cible = rr x risque.
Limites : le vrai CVD exige des transactions classées ; un iceberg est invisible par construction : tout ceci est un PROXY, nommé comme tel.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .apex import ramp
from .events import Event, atr_series
from .order_flow_ofi import absorption_score

PARAMS = {"lookback": 6, "abs_full": 0.6, "move_lo": 0.5, "move_hi": 1.5, "cvd_bars": 8, "omega_min": 0.4, "stop_buf_atr": 0.2, "rr": 2.0, "cooldown": 6, "hours": [7, 21]}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close")); v = df["volume"].to_numpy(float); atr = atr_series(df, 14)
    A = absorption_score(df, atr); delta = np.nan_to_num(v * (2 * (c - l) / np.where(h > l, h - l, np.nan) - 1.0)); cvd = pd.Series(delta).rolling(p["cvd_bars"]).sum().to_numpy(); sc = pd.Series(np.abs(delta)).rolling(100).mean().to_numpy() * p["cvd_bars"] ** 0.5
    prevA = pd.Series(A).shift(1).rolling(p["lookback"]).max().to_numpy(); hr = df.index.hour; out, last = [], -10**9
    for i in range(110, len(df)):
        if not (p["hours"][0] <= hr[i] < p["hours"][1]) or not np.isfinite(atr[i]) or not np.isfinite(prevA[i]) or i - last < p["cooldown"]:
            continue
        move = (c[i] - o[i]) / atr[i]; sg = 1 if move > 0 else -1
        zone = slice(i - p["lookback"], i); zhi, zlo = float(h[zone].max()), float(l[zone].min())
        om = (float(ramp(prevA[i], 0.0, p["abs_full"])) * float(ramp(abs(move), p["move_lo"], p["move_hi"])) * float(ramp(sg * cvd[i] / (sc[i] + 1e-9), 0.0, 1.0))) ** (1 / 3)
        if om < p["omega_min"]:
            continue
        stop = (zlo - p["stop_buf_atr"] * atr[i]) if sg > 0 else (zhi + p["stop_buf_atr"] * atr[i]); risk = abs(c[i] - stop)
        if risk <= 0 or risk > 3 * atr[i]:
            continue
        tgt = c[i] + sg * p["rr"] * risk
        out.append(Event(df.index[i], "bullish" if sg > 0 else "bearish", stop, tgt, f"abs_{'long' if sg > 0 else 'short'}", {"confidence": min(om, 1.0), "omega": float(om), "absorption": float(prevA[i])})); last = i
    return out
