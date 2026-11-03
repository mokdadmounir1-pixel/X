"""S3 SIG-TDA : signature de chemin (niveau 3, 39 variables) lue par une régression ridge LINÉAIRE, bridée par une porte topologique (homologie persistante H1 du nuage des rendements de 4 indices).

Chemin augmenté X = (t, prix normalisé, volume normalisé) sur les `L` dernières barres ; signature exacte (Chen). Score = prévision ridge du rendement des `h` barres suivantes, standardisée ; la régression est ré-entraînée tous les `retrain` points de décision sur les `train_n` derniers points dont le rendement futur est CONNU à l'instant de décision (aucune fuite).
Porte TDA : nuage = rendements des `assets` (US500, USTEC, US30, DE40) sur `W` barres ; norme L1 du paysage = SOMME ((d-b)/2)^2 ; si elle dépasse son quantile `gate_q` (95 %) des `gate_hist` dernières décisions : exposition ZÉRO. Sans `ripser` ou sans les données des 4 indices : la porte est INCONNUE et AUCUN trade n'est pris.
Entrée : |score| >= `s_min` ; taille ~ min(1, |score|) (par la confiance, voir ibs_rsi2_trend) ; stop `stop_atr` x ATR(14), sortie temporelle (`max_hold_bars` de la spec).
Écarts DÉCLARÉS : barres M15 (le cahier : M5 ; M5 non collecté pour US500/US30/DE40) ; pas de rebalancement à 25 % (le moteur gère des trades, pas une position cible continue) ; seuil d'entrée `s_min` et hyperparamètres figés a priori dans la spec. Aucune valeur démontrée.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..stat.signature import signature
from ..stat.tda import available, landscape_l1
from .events import Event, atr_series
from .external_data import load_bars

PARAMS = {"assets": ["US500", "USTEC", "US30", "DE40"], "tf": "M15", "root": None, "L": 32, "h": 8, "step": 4, "train_n": 600, "retrain": 24, "ridge": 10.0, "s_min": 0.5, "W": 48,
          "gate_q": 0.95, "gate_hist": 500, "stop_atr": 2.0, "target_atr": 4.0, "size_cap": 1.0, "base_risk": 0.5}


def path_features(c: np.ndarray, v: np.ndarray, i: int, L: int) -> np.ndarray:
    w = np.log(c[i - L + 1: i + 1]); sd = w.std() if w.std() > 0 else 1.0; pn = (w - w[0]) / sd
    vv = v[i - L + 1: i + 1]; vm = vv.mean() if vv.mean() > 0 else 1.0; vn = vv / vm - 1.0
    return signature(np.c_[np.linspace(0, 1, L), pn, vn])


def gate_matrix(df: pd.DataFrame, p: dict):
    """Rendements alignés des actifs (colonnes) sur l'index de `df` ; None si un actif manque."""
    cols = {}
    for a in p["assets"]:
        b = load_bars(a, p["tf"], p["root"])
        if b is None:
            return None
        cols[a] = np.log(b["close"]).reindex(df.index, method="ffill", limit=4).diff()
    return pd.DataFrame(cols)


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}
    if not available():
        return []
    G = gate_matrix(df, p)
    if G is None:
        return []
    c, v = df["close"].to_numpy(float), df["volume"].to_numpy(float) if "volume" in df else np.ones(len(df)); atr = atr_series(df, 14); n = len(df); L, h = p["L"], p["h"]; Gv = G.to_numpy(float)
    bar_s = max(60.0, float(df.index.to_series().diff().median().total_seconds())); slot = ((df.index - df.index.normalize()).total_seconds() // bar_s).astype(int)
    dec = [i for i in range(max(L, p["W"]) + 5, n) if slot[i] % p["step"] == 0]  # grille de décision ABSOLUE (indépendante du début de la fenêtre)
    X = []; Y = []; norms = []; model = None; out = []; since = 10**9
    for di, i in enumerate(dec):
        X.append(path_features(c, v, i, L)); Y.append((c[i + h] / c[i] - 1.0) if i + h < n else np.nan)
        cloud = Gv[i - p["W"] + 1: i + 1]
        if np.isfinite(cloud).all():
            sd = cloud.std(axis=0); sd[sd == 0] = 1.0; norms.append(landscape_l1((cloud - cloud.mean(axis=0)) / sd))
        else:
            norms.append(None)
        known = [k for k in range(di + 1) if dec[k] + h <= i and np.isfinite(Y[k])]              # rendement futur connu à l'instant i
        if len(known) < max(100, p["train_n"] // 3):
            continue
        since += 1
        if model is None or since >= p["retrain"]:
            ks = known[-p["train_n"]:]; A = np.array([X[k] for k in ks]); y = np.array([Y[k] for k in ks]); mu, sg = A.mean(0), A.std(0); sg[sg == 0] = 1.0; ys = y.std() or 1.0
            Az = (A - mu) / sg; w = np.linalg.solve(Az.T @ Az + p["ridge"] * np.eye(Az.shape[1]), Az.T @ ((y - y.mean()) / ys)); model = (mu, sg, w); since = 0
        mu, sg, w = model; score = float(((X[di] - mu) / sg) @ w)
        hist = [x for x in norms[-p["gate_hist"] - 1: -1] if x is not None]
        if norms[-1] is None or len(hist) < 30 or norms[-1] > np.quantile(hist, p["gate_q"]):      # porte inconnue ou fermée : exposition nulle
            continue
        if abs(score) < p["s_min"] or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        d = 1 if score > 0 else -1; f = float(min(p["size_cap"], abs(score)))
        out.append(Event(df.index[i], "bullish" if d > 0 else "bearish", float(c[i] - d * p["stop_atr"] * atr[i]), float(c[i] + d * p["target_atr"] * atr[i]), "sig_tda",
                         {"score": score, "gate_norm": float(norms[-1]), "size_factor": f, "confidence": 0.5 + 0.5 * max(f, 0.2)}))
    return out
