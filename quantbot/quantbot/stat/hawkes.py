"""Processus de Hawkes bivarié (achats b, ventes s) à noyau exponentiel, VPIN par Bulk Volume Classification, imbalance d'intensité — briques de HAWK-TOX.

lambda_i(t) = mu_i + SOMME_j alpha_ij SOMME_{t_k^j < t} exp(-beta (t - t_k^j)) ; Gamma = alpha / beta ; rho = rayon spectral de Gamma (rho < 1 : stationnaire ; proche de 1 : régime quasi critique, endogène).
Calibration par maximum de vraisemblance (récurrence O(N)) ; mise à jour EN LIGNE en O(1) par événement (`OnlineHawkes`). Aucune donnée inventée : les fonctions travaillent sur les événements fournis.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import minimize


def tick_rule(mid: np.ndarray) -> np.ndarray:
    """Signe de chaque variation du mid (+1 achat, -1 vente) ; une variation nulle reprend le signe précédent ; les premières valeurs sans signe sont 0."""
    d = np.diff(np.asarray(mid, float)); s = np.sign(d).astype(int); last = 0
    for i in range(len(s)):
        if s[i] == 0:
            s[i] = last
        else:
            last = s[i]
    return s


def _nll(theta: np.ndarray, t: np.ndarray, typ: np.ndarray, T: float) -> float:
    """-log-vraisemblance : SOMME log lambda_{i_k}(t_k) - SOMME_i INTEGRALE lambda_i ; récurrence R_j(t_k) = exp(-beta dt) (R_j(t_{k-1}) + 1{type_{k-1} = j})."""
    mu = np.exp(theta[:2]); a = np.exp(theta[2:6]).reshape(2, 2); beta = math.exp(theta[6])
    R0 = R1 = 0.0; ll = 0.0; c0 = c1 = 0.0
    for k in range(len(t)):
        if k > 0:
            e = math.exp(-beta * (t[k] - t[k - 1])); R0, R1 = e * (R0 + (1.0 if typ[k - 1] == 0 else 0.0)), e * (R1 + (1.0 if typ[k - 1] == 1 else 0.0))
        i = typ[k]; lam = mu[i] + a[i, 0] * R0 + a[i, 1] * R1
        if lam <= 0.0:
            return 1e12
        ll += math.log(lam); g = (1.0 - math.exp(-beta * (T - t[k]))) / beta
        if i == 0: c0 += g
        else: c1 += g
    ll -= mu.sum() * T + (a[0, 0] + a[1, 0]) * c0 + (a[0, 1] + a[1, 1]) * c1
    return -ll


def fit_hawkes(t: np.ndarray, typ: np.ndarray, T: float | None = None, max_events: int = 20000, x0=None) -> dict:
    """MLE du Hawkes bivarié (mu, alpha 2x2, beta commun). `t` croissant en secondes (début = 0 conseillé), `typ` dans {0 = achat, 1 = vente}. Garde les `max_events` derniers événements.
    Renvoie mu, alpha, beta, rho (rayon spectral de alpha/beta), n et le succès de l'optimiseur ; lève ValueError si trop peu d'événements."""
    t = np.asarray(t, float); typ = np.asarray(typ, int)
    if len(t) < 200:
        raise ValueError("moins de 200 événements : calibration impossible")
    t, typ = t[-max_events:], typ[-max_events:]; t = t - t[0]; T = float(T if T is not None else t[-1] + 1e-9); rate = len(t) / T
    x = np.log(np.r_[[rate / 2] * 2, [0.3 * rate / 2] * 4, [max(2.0 / (np.median(np.diff(t)) + 1e-9) * 0.5, 0.05)]]) if x0 is None else np.asarray(x0, float)
    r = minimize(_nll, x, args=(t, typ, T), method="L-BFGS-B", bounds=[(-12, 6)] * 6 + [(-6, 8)], options={"maxiter": 60})
    mu = np.exp(r.x[:2]); a = np.exp(r.x[2:6]).reshape(2, 2); beta = float(math.exp(r.x[6]))
    return {"mu": mu, "alpha": a, "beta": beta, "rho": spectral_radius(a, beta), "n": int(len(t)), "ok": bool(r.success or r.nit >= 5), "nll": float(r.fun)}


def spectral_radius(alpha: np.ndarray, beta: float) -> float:
    return float(np.max(np.abs(np.linalg.eigvals(np.asarray(alpha, float) / beta))))


class OnlineHawkes:
    """Intensités à l'instant t en O(1) par événement : S_j = SOMME exp(-beta (t - t_k^j)) est décroissance + incrément."""

    def __init__(self, mu, alpha, beta: float) -> None:
        self.mu, self.alpha, self.beta = np.asarray(mu, float), np.asarray(alpha, float), float(beta); self.S = np.zeros(2); self.t: float | None = None

    def _decay_to(self, t: float) -> None:
        if self.t is not None and t > self.t:
            self.S *= math.exp(-self.beta * (t - self.t))
        self.t = t if self.t is None or t > self.t else self.t

    def update(self, t: float, typ: int) -> None:
        self._decay_to(t); self.S[typ] += 1.0

    def intensity(self, t: float | None = None) -> np.ndarray:
        if t is not None:
            self._decay_to(t)
        return self.mu + self.alpha @ self.S

    def imbalance(self, t: float | None = None) -> float:
        lam = self.intensity(t); s = lam[0] + lam[1]
        return float((lam[0] - lam[1]) / s) if s > 0 else 0.0


def t3_cdf(x):
    """Fonction de répartition de la loi de Student à 3 degrés de liberté (forme fermée)."""
    x = np.asarray(x, float); return 0.5 + (x / (math.sqrt(3.0) * (1.0 + x * x / 3.0)) + np.arctan(x / math.sqrt(3.0))) / math.pi


def bvc_buy_volume(dp, volume, sigma):
    """Bulk Volume Classification : volume acheteur = V x F(dP / sigma) (F : Student 3) ; sigma <= 0 ou NaN -> moitié/moitié."""
    dp, volume, sigma = np.asarray(dp, float), np.asarray(volume, float), np.asarray(sigma, float)
    z = np.where(np.isfinite(sigma) & (sigma > 0), dp / np.where(sigma > 0, sigma, 1.0), 0.0); return volume * t3_cdf(z)


def vpin_series(dp, volume, window: int = 50, sigma_window: int = 500):
    """VPIN glissant = SOMME |2 Vb - V| / SOMME V sur `window` barres, sigma = écart-type des dP sur `sigma_window` barres PRÉCÉDENTES (causal). Valeurs dans [0,1] ; NaN avant le premier remplissage.
    Approximation déclarée : barres de TEMPS (M1) au lieu de seaux de volume égal."""
    import pandas as pd
    dp = pd.Series(np.asarray(dp, float)); v = pd.Series(np.asarray(volume, float)); sig = dp.rolling(sigma_window, min_periods=max(30, sigma_window // 5)).std().shift(1)
    vb = pd.Series(bvc_buy_volume(dp.to_numpy(), v.to_numpy(), sig.to_numpy())); imb = (2 * vb - v).abs()
    return (imb.rolling(window).sum() / v.rolling(window).sum()).to_numpy()
