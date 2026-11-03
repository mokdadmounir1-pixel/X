"""Estimation du décalage (lead-lag) entre deux séries asynchrones et régression en ligne à bêtas évolutifs — briques de LEADLAG-K.

Estimateur de Hayashi-Yoshida décalé : U(l) = SOMME_{i,j} dX_i dY_j 1{(tx_{i-1}, tx_i] chevauche (ty_{j-1} - l, ty_j - l]} ; corr(l) = U(l) / racine(SOMME dX^2 x SOMME dY^2).
l* = argmax |corr(l)| ; LLR = SOMME_{l>0} corr^2 / SOMME_{l<0} corr^2 : > 1 => X mène (convention du cahier : X mène si le décalage positif de Y est le meilleur).
Régression Kalman : r_t = b_t' z_t + eps, b_t = b_{t-1} + w_t (marche aléatoire), O(d^2) par pas.
"""
from __future__ import annotations

import numpy as np


def hy_cov(tx, x, ty, y, lag: float = 0.0) -> float:
    """Covariance de Hayashi-Yoshida entre les incréments de X (prix x aux dates tx) et ceux de Y dont les intervalles sont décalés de -lag. Deux pointeurs : O(n + m)."""
    tx, x, ty, y = (np.asarray(a, float) for a in (tx, x, ty, y)); ty = ty - lag      # intervalles (ty_{j-1} - l, ty_j - l] : formule du cahier ; l > 0 <=> Y suit X de l (X mène)
    dx, dy = np.diff(x), np.diff(y); i = j = 0; tot = 0.0
    while i < len(dx) and j < len(dy):
        ax, bx = tx[i], tx[i + 1]; ay, by = ty[j], ty[j + 1]
        if min(bx, by) > max(ax, ay):
            tot += dx[i] * dy[j]
        if bx < by: i += 1
        else: j += 1
    return float(tot)


def hy_corr(tx, x, ty, y, lag: float = 0.0) -> float:
    vx = float(np.sum(np.diff(np.asarray(x, float)) ** 2)); vy = float(np.sum(np.diff(np.asarray(y, float)) ** 2))
    return hy_cov(tx, x, ty, y, lag) / np.sqrt(vx * vy) if vx > 0 and vy > 0 else 0.0


def lead_lag(tx, x, ty, y, lags) -> dict:
    """{lag*, corr_by_lag, llr}. `lags` : décalages (en unités de temps) symétriques autour de 0 ; llr = SOMME_{l>0} corr^2 / SOMME_{l<0} corr^2 (NaN si le dénominateur est nul)."""
    lags = np.asarray(lags, float); c = np.array([hy_corr(tx, x, ty, y, l) for l in lags]); pos, neg = float(np.sum(c[lags > 0] ** 2)), float(np.sum(c[lags < 0] ** 2))
    return {"lag_star": float(lags[int(np.argmax(np.abs(c)))]), "corr": dict(zip(map(float, lags), map(float, c))), "llr": pos / neg if neg > 0 else float("nan")}


def lag_by_bars(rx: np.ndarray, rz: np.ndarray, max_lag: int) -> dict:
    """Version barres alignées : corr(r^X_t, z_{t-l}) pour l = -max_lag..max_lag ; l > 0 : z (driver) MÈNE X de l barres. Renvoie {lag_star, llr, corr}."""
    rx, rz = np.asarray(rx, float), np.asarray(rz, float); n = len(rx); out = {}
    for l in range(-max_lag, max_lag + 1):
        a, b = (rx[l:], rz[: n - l]) if l >= 0 else (rx[: n + l], rz[-l:])
        out[l] = float(np.corrcoef(a, b)[0, 1]) if len(a) > 10 and a.std() > 0 and b.std() > 0 else 0.0
    ls = np.array(list(out)); c = np.array(list(out.values())); pos, neg = float(np.sum(c[ls > 0] ** 2)), float(np.sum(c[ls < 0] ** 2))
    return {"lag_star": int(ls[int(np.argmax(np.abs(c)))]), "llr": pos / neg if neg > 0 else float("nan"), "corr": out}


class KalmanBetas:
    """Régression à coefficients en marche aléatoire : b_t = b_{t-1} + w (cov q I), r_t = b' z + e (variance r)."""

    def __init__(self, dim: int, q: float = 1e-6, r: float = 1e-6, b0: float = 0.0, p0: float = 1.0) -> None:
        self.b = np.full(dim, b0, float); self.P = np.eye(dim) * p0; self.q, self.r = q, r

    def predict(self, z: np.ndarray) -> float:
        return float(self.b @ np.asarray(z, float))

    def update(self, z: np.ndarray, y: float) -> float:
        z = np.asarray(z, float); self.P = self.P + np.eye(len(self.b)) * self.q; S = float(z @ self.P @ z + self.r); K = self.P @ z / S; err = float(y - self.b @ z)
        self.b = self.b + K * err; self.P = self.P - np.outer(K, z) @ self.P; return err
