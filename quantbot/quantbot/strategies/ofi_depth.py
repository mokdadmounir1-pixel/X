"""Microstructure (stratégie n°5) : déséquilibre RÉEL du carnet (profondeur enregistrée par le terminal dans data/live/depth) en CONFIRMATION de la direction de la barre.

Déséquilibre moyen du carnet sur 15 min (somme des tailles bid - ask sur les meilleurs niveaux), centré-réduit sur `z_bars` barres (causal). Achat si z >= `z_entry` ET la barre est haussière ; vente symétrique ; stop `stop_atr` x ATR, cible `rr` x risque.
Sans fichiers de profondeur (courtier qui ne l'expose pas, ou collecte trop récente) : AUCUN événement. Les tailles du carnet CFD d'un courtier de détail ne sont pas le carnet du marché interbancaire.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .apex import ramp
from .events import Event, atr_series
from .external_data import load_depth_imbalance

PARAMS = {"z_bars": 200, "z_entry": 1.5, "z_full": 3.0, "stop_atr": 1.5, "rr": 2.0, "cooldown": 6, "hours": [7, 21], "root": None, "symbol": "XAUUSD"}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; imb = load_depth_imbalance(p["root"], p["symbol"])
    if imb is None or len(imb) < p["z_bars"] // 4:
        return []
    I = imb.reindex(df.index); z = ((I - I.rolling(p["z_bars"], min_periods=50).mean()) / I.rolling(p["z_bars"], min_periods=50).std()).to_numpy()
    o, c = df["open"].to_numpy(float), df["close"].to_numpy(float); atr = atr_series(df, 14); hr = df.index.hour; out, last = [], -10**9
    for i in range(len(df)):
        if not np.isfinite(z[i]) or abs(z[i]) < p["z_entry"] or not (p["hours"][0] <= hr[i] < p["hours"][1]) or i - last < p["cooldown"] or not np.isfinite(atr[i]):
            continue
        sg = 1 if z[i] > 0 else -1
        if (c[i] - o[i]) * sg <= 0:
            continue
        stop = c[i] - sg * p["stop_atr"] * atr[i]; tgt = c[i] + sg * p["rr"] * p["stop_atr"] * atr[i]
        out.append(Event(df.index[i], "bullish" if sg > 0 else "bearish", stop, tgt, f"ofid_{'long' if sg > 0 else 'short'}", {"confidence": float(ramp(abs(z[i]), p["z_entry"], p["z_full"])), "z": float(z[i])})); last = i
    return out
