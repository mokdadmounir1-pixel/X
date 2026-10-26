"""Proximité aux niveaux structurels (chiffres ronds + nœuds de volume récents) fusionnée avec le repli APEX.

CE N'EST PAS UN GEX. Aucune donnée d'options n'est utilisée ; c'est une HYPOTHÈSE testable (les prix réagissent près des chiffres ronds et des zones de volume), pas un substitut démontré
du positionnement des teneurs de marché. Elle est donc évaluée comme n'importe quelle stratégie (essai compté, mêmes portes).
Causal : le profil de volume à la barre i n'utilise que les barres <= i (recalculé toutes les `refresh` barres, figé entre deux recalculs).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .apex import PARAMS as APEX_PARAMS, scores
from .events import Event

PARAMS = {**APEX_PARAMS, "stop_atr": 1.8, "rr": 3.0, "fused_min": 0.70, "w_level": 0.5, "round_steps": [50.0, 10.0], "round_weights": [1.0, 0.4], "round_width_atr": 0.5,
          "nodes_bars": 480, "refresh": 16, "node_bin_atr": 0.5, "top_k": 4, "node_width_atr": 0.5}


def round_score(price: np.ndarray, atr: np.ndarray, steps, weights, width_atr: float) -> np.ndarray:
    """Score continu [0, 1] : max_k w_k x exp(-(distance au multiple de step_k / (width x ATR))²)."""
    out = np.zeros(len(price))
    for st, w in zip(steps, weights):
        d = np.abs(price - np.round(price / st) * st)
        out = np.maximum(out, w * np.exp(-((d / (width_atr * atr)) ** 2)))
    return out


def node_score(df: pd.DataFrame, atr: np.ndarray, p: dict) -> np.ndarray:
    """Score [0, 1] de proximité aux `top_k` nœuds de volume des `nodes_bars` dernières barres (force = part du volume relative au plus gros nœud)."""
    c = df["close"].to_numpy(float); tp = ((df["high"] + df["low"] + df["close"]) / 3.0).to_numpy(float); v = df["volume"].to_numpy(float); n = len(df)
    out = np.zeros(n); nodes = np.array([]); strength = np.array([]); lb = p["nodes_bars"]
    for i in range(lb, n):
        if (i - lb) % p["refresh"] == 0 and np.isfinite(atr[i]) and atr[i] > 0:
            seg = slice(i - lb + 1, i + 1); bw = p["node_bin_atr"] * atr[i]
            bins = np.floor(tp[seg] / bw).astype(np.int64); u, inv = np.unique(bins, return_inverse=True); vol = np.bincount(inv, weights=v[seg])
            k = np.argsort(-vol)[: p["top_k"]]; nodes = (u[k] + 0.5) * bw; strength = vol[k] / vol[k[0]]
        if len(nodes) and np.isfinite(atr[i]) and atr[i] > 0:
            out[i] = float(np.max(strength * np.exp(-((np.abs(c[i] - nodes) / (p["node_width_atr"] * atr[i])) ** 2))))
    return out


def level_score(df: pd.DataFrame, atr: np.ndarray, p: dict) -> np.ndarray:
    c = df["close"].to_numpy(float)
    return np.maximum(round_score(c, atr, p["round_steps"], p["round_weights"], p["round_width_atr"]), node_score(df, atr, p))


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; sc = scores(df, p); atr = sc["atr"]; L = level_score(df, atr, p); c = df["close"].to_numpy(float)
    sess = (df.index.hour >= 7) & (df.index.hour < 17); out, last = [], -10**9
    for i in range(max(p["ema_slow"] + p["atr_long"], p["nodes_bars"]), len(df)):
        if not sess[i] or not np.isfinite(atr[i]) or i - last < p["cooldown"]:
            continue
        for side, sg, direction in (("bull", 1, "bullish"), ("bear", -1, "bearish")):
            S = sc[side]["S"][i]
            if not np.isfinite(S) or S <= 0:
                continue
            f = float((S ** (1.0 - p["w_level"])) * (L[i] ** p["w_level"]))
            if f >= p["fused_min"]:
                stop = c[i] - sg * p["stop_atr"] * atr[i]; tgt = c[i] + sg * p["rr"] * p["stop_atr"] * atr[i]
                out.append(Event(df.index[i], direction, stop, tgt, f"apex_lvl_{'long' if sg > 0 else 'short'}", {"confidence": min(f, 1.0), "S": float(S), "L": float(L[i]), "fused": f})); last = i
                break
    return out
