"""Réversion à la moyenne : résidu du filtre de Kalman 1D + demi-vie d'Ornstein-Uhlenbeck (stratégie n°2).

Niveau « vrai » : filtre de Kalman 1D à marche aléatoire (variance du processus `q`, du bruit d'observation `r`, exprimées en fraction de la variance des rendements récents : le filtre s'adapte à l'actif).
Résidu z = (clôture - niveau filtré) / écart-type glissant des résidus. Un fade n'est autorisé que si la série est RÉVERSIVE : t-statistique de Dickey-Fuller sur la fenêtre < `t_max` (significative)
ET demi-vie OU dans [`hl_min`, `hl_max`] barres. Score continu : produit de rampes (|z|, réversion, demi-vie).
Entrée contre l'excès, cible = niveau filtré, stop = `stop_sd` écarts-types au-delà. Limite : un Kalman à gain constant a le même retard qu'une EMA (pas de « zéro lag »).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..stat.pairs import ou_half_life
from .apex import ramp
from .events import Event, atr_series

PARAMS = {"window": 200, "recompute_every": 8, "q_frac": 0.02, "z_entry": 2.0, "z_full": 3.0, "t_max": -2.0, "hl_min": 2.0, "hl_max": 60.0, "stop_sd": 1.5, "omega_min": 0.5,
          "cooldown": 8, "hours": [7, 21], "sd_window": 100}


def kalman_level(x: np.ndarray, q_frac: float = 0.02) -> np.ndarray:
    """Niveau filtré (causal). Variance d'observation r = variance des différences premières (estimée en ligne, causale) ; variance du processus q = q_frac x r."""
    n = len(x); lvl = np.empty(n); lvl[0] = x[0]; P = 1.0; dv = pd.Series(np.diff(x, prepend=x[0])).expanding(min_periods=20).var().bfill().to_numpy()
    for i in range(1, n):
        r = max(dv[i], 1e-12); q = q_frac * r; Pp = P + q; K = Pp / (Pp + r); lvl[i] = lvl[i - 1] + K * (x[i] - lvl[i - 1]); P = (1 - K) * Pp
    return lvl


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; c = df["close"].to_numpy(float); n = len(c); lvl = kalman_level(c, p["q_frac"]); res = c - lvl
    sd = pd.Series(res).rolling(p["sd_window"]).std().to_numpy(); z = res / sd; atr = atr_series(df, 14); hr = df.index.hour
    tstat = np.full(n, np.nan); hl = np.full(n, np.nan)
    for i in range(p["window"], n, p["recompute_every"]):
        r = ou_half_life(c[i - p["window"]:i + 1]); tstat[i] = r.get("t_stat", np.nan); hl[i] = r.get("half_life", np.nan)
    tstat = pd.Series(tstat).ffill(limit=p["recompute_every"] - 1).to_numpy(); hl = pd.Series(hl).ffill(limit=p["recompute_every"] - 1).to_numpy()
    out, last = [], -10**9
    for i in range(p["window"] + p["sd_window"], n):
        if not (p["hours"][0] <= hr[i] < p["hours"][1]) or not np.isfinite(z[i]) or not np.isfinite(tstat[i]) or i - last < p["cooldown"]:
            continue
        rev = float(ramp(-(tstat[i] - p["t_max"]), 0.0, 1.5))                                      # 0 à t = t_max, 1 quand t est 1,5 plus négatif
        hl_ok = float(ramp(hl[i], p["hl_min"] / 2, p["hl_min"]) * (1.0 - ramp(hl[i], p["hl_max"], p["hl_max"] * 1.5))) if np.isfinite(hl[i]) else 0.0
        zs = float(ramp(abs(z[i]), p["z_entry"] - 0.5, p["z_full"]))
        om = (rev * hl_ok * zs) ** (1 / 3)
        if om < p["omega_min"]:
            continue
        if z[i] > 0:
            stop = c[i] + p["stop_sd"] * sd[i]; tgt = lvl[i]; ev = Event(df.index[i], "bearish", stop, tgt, "kou_short", {"confidence": min(om, 1.0), "omega": om, "z": float(z[i]), "half_life": float(hl[i])})
            if stop > c[i] > tgt and (c[i] - tgt) / (stop - c[i]) >= 1.0: out.append(ev); last = i
        else:
            stop = c[i] - p["stop_sd"] * sd[i]; tgt = lvl[i]; ev = Event(df.index[i], "bullish", stop, tgt, "kou_long", {"confidence": min(om, 1.0), "omega": om, "z": float(z[i]), "half_life": float(hl[i])})
            if stop < c[i] < tgt and (tgt - c[i]) / (c[i] - stop) >= 1.0: out.append(ev); last = i
    return out
