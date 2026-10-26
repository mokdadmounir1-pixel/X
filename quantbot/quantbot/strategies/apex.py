"""THE APEX PULLBACK ALPHA — repli dans une tendance saine, score de similarité continu S dans [0, 1].

Quatre facteurs continus (jamais un booléen), combinés par moyenne GÉOMÉTRIQUE (un facteur nul annule le setup) :
  T tendance   : écart EMA50 - EMA200 en ATR (0 -> 0, `trend_full` -> 1), dans le sens du trade
  P repli      : le prix a touché la zone EMA50 récemment (`touch`) ET clôture près d'elle (`depth`)
  M momentum   : RSI qui sort de la zone de repli (rampe 40 -> 55 pour un achat), pénalisé en excès (65 -> 80)
  V régime     : ATR / ATR long ; pénalise l'expansion de volatilité (rampe `vol_lo` -> `vol_hi`)
Signal si S >= s_min (0,75) ; le score est transmis comme confiance : taille continue via risk.score_sizing_floor.
Stop = stop_atr x ATR, cible = rr x risque (> 2,5). Fenêtre 07h-17h UTC. Causal (données <= t). Les seuils de rampe sont des paramètres de la spec.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import Event, atr_series

PARAMS = {"ema_slow": 200, "ema_mid": 50, "rsi": 14, "atr_long": 100, "s_min": 0.75, "stop_atr": 1.5, "rr": 2.6, "cooldown": 8,
          "trend_full": 2.0, "touch_bars": 6, "touch_ramp": 1.0, "depth_lo": 0.25, "depth_hi": 1.25, "mom_lo": 40.0, "mom_hi": 55.0, "mom_ex_lo": 65.0, "mom_ex_hi": 80.0,
          "vol_lo": 1.3, "vol_hi": 2.0}
SESSION = (7, 17)


def ramp(x, lo: float, hi: float):
    """Rampe continue : 0 sous lo, 1 au-dessus de hi, linéaire entre les deux."""
    return np.clip((np.asarray(x, float) - lo) / (hi - lo), 0.0, 1.0)


def rsi(close: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(close, prepend=close[0]); up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).to_numpy()


def scores(df: pd.DataFrame, p: dict) -> dict:
    """Facteurs et score pour les deux sens, tableaux alignés sur df (NaN = indisponible)."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close")); atr = atr_series(df, 14); s = pd.Series(c)
    e200, e50 = (s.ewm(span=n, adjust=False).mean().to_numpy() for n in (p["ema_slow"], p["ema_mid"])); r = rsi(c, p["rsi"])
    atr_l = pd.Series(atr).rolling(p["atr_long"]).mean().to_numpy(); V = 1.0 - ramp(atr / atr_l, p["vol_lo"], p["vol_hi"])
    out = {"V": V, "atr": atr, "atr_ratio": atr / atr_l}
    low_n = pd.Series(l).rolling(p["touch_bars"]).min().to_numpy(); high_n = pd.Series(h).rolling(p["touch_bars"]).max().to_numpy()
    for side, sg in (("bull", 1.0), ("bear", -1.0)):
        T = ramp(sg * (e50 - e200) / atr, 0.0, p["trend_full"]) * (sg * (c - e200) > 0)
        gap = (low_n - e50) / atr if sg > 0 else (e50 - high_n) / atr          # <= 0 : le repli a touché l'EMA50 dans les `touch_bars` dernières barres
        touch = 1.0 - ramp(gap, 0.0, p["touch_ramp"])
        depth = 1.0 - ramp(np.abs(c - e50) / atr, p["depth_lo"], p["depth_hi"])
        P = np.sqrt(np.clip(touch, 0, 1) * depth)
        rr_ = r if sg > 0 else 100 - r
        M = ramp(rr_, p["mom_lo"], p["mom_hi"]) * (1.0 - ramp(rr_, p["mom_ex_lo"], p["mom_ex_hi"]))
        S = (np.clip(T, 0, 1) * P * M * V) ** 0.25
        out[side] = {"T": T, "P": P, "M": M, "S": S}
    return out


def events(df: pd.DataFrame, p: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(p or {})}; o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    sc = scores(df, p); atr = sc["atr"]; sess = (df.index.hour >= SESSION[0]) & (df.index.hour < SESSION[1]); out, last = [], -10**9
    for i in range(p["ema_slow"] + p["atr_long"], len(df)):
        if not sess[i] or not np.isfinite(atr[i]) or i - last < p["cooldown"]:
            continue
        sb, ss = sc["bull"]["S"][i], sc["bear"]["S"][i]
        if np.isfinite(sb) and sb >= p["s_min"] and sb >= (ss if np.isfinite(ss) else 0):
            stop = c[i] - p["stop_atr"] * atr[i]; out.append(Event(df.index[i], "bullish", stop, c[i] + p["rr"] * (c[i] - stop), "apex_long", {"confidence": float(min(sb, 1.0)), "S": float(sb), "atr_ratio": float(sc["atr_ratio"][i])})); last = i
        elif np.isfinite(ss) and ss >= p["s_min"]:
            stop = c[i] + p["stop_atr"] * atr[i]; out.append(Event(df.index[i], "bearish", stop, c[i] - p["rr"] * (stop - c[i]), "apex_short", {"confidence": float(min(ss, 1.0)), "S": float(ss), "atr_ratio": float(sc["atr_ratio"][i])})); last = i
    return out
