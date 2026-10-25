"""Arbitrage statistique sur paire : test de cointégration (Engle-Granger/ADF), bêta dynamique (filtre de Kalman), z-score, simulation causale.

Tout est causal : à la barre t on n'utilise que les barres <= t ; l'ordre est exécuté à l'OUVERTURE de t+1 (même règle que le moteur unique).
Ce simulateur est un outil de RECHERCHE à deux jambes : il n'est pas branché au runtime MT5/DEMO (le moteur unique est mono-instrument).
Unité R : perte nominale d'un stop à |z| = z_stop depuis |z| = z_entry, exprimée en écarts-types du spread à l'entrée.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Valeur critique asymptotique Engle-Granger (2 variables, constante) à 5 % : MacKinnon. L'ADF classique (-2,86) serait trop permissif sur des résidus estimés.
EG_CRIT_5 = -3.34


def adf_stat(x: np.ndarray, lags: int = 1) -> float:
    """Statistique t de Dickey-Fuller augmentée (constante, `lags` différences retardées). Plus négatif = plus stationnaire."""
    x = np.asarray(x, dtype=float)
    dx = np.diff(x)
    n = len(dx) - lags
    if n < 30:
        return float("nan")
    y = dx[lags:]
    cols = [x[lags:-1], np.ones(n)] + [dx[lags - k - 1: len(dx) - k - 1] for k in range(lags)]
    X = np.column_stack(cols)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    s2 = resid @ resid / (n - X.shape[1])
    cov = s2 * np.linalg.inv(X.T @ X)
    return float(beta[0] / np.sqrt(cov[0, 0]))


def engle_granger(a: np.ndarray, b: np.ndarray, lags: int = 1) -> dict:
    """Régression OLS a = alpha + beta*b puis ADF sur les résidus. `cointegrated` si stat < EG_CRIT_5."""
    X = np.column_stack([np.ones(len(b)), b])
    coef, *_ = np.linalg.lstsq(X, a, rcond=None)
    stat = adf_stat(a - X @ coef, lags)
    return {"alpha": float(coef[0]), "beta": float(coef[1]), "adf": stat, "cointegrated": bool(stat < EG_CRIT_5)}


class Kalman:
    """a_t = alpha_t + beta_t * b_t + e_t ; (alpha, beta) marche aléatoire. `step` renvoie l'innovation et sa variance A PRIORI (donc causal)."""

    def __init__(self, delta: float = 1e-5, obs_var: float = 1e-3, init_beta: float = 1.0) -> None:
        self.Vw = delta / (1.0 - delta); self.Ve = obs_var
        self.theta = np.array([0.0, init_beta]); self.P = np.eye(2)

    def step(self, a: float, b: float) -> tuple[float, float]:
        H = np.array([1.0, b])
        P_pred = self.P + self.Vw * np.eye(2)
        e = a - H @ self.theta
        Q = H @ P_pred @ H + self.Ve
        K = P_pred @ H / Q
        self.theta = self.theta + K * e
        self.P = P_pred - np.outer(K, H) @ P_pred
        return float(e), float(Q)


@dataclass
class PairParams:
    z_entry: float = 2.0
    z_stop: float = 3.5
    z_exit: float = 0.0
    delta: float = 1e-5
    obs_var: float = 1e-3
    sigma_halflife: int = 250     # écart-type EWMA des innovations (la variance a priori Q du Kalman est dominée par la colinéarité alpha/beta)
    warmup: int = 500
    coint_window: int = 2000
    coint_every: int = 96          # ~24 h en M15
    max_hold: int = 960            # ~10 jours en M15
    cost_per_leg: float = 0.0      # fraction du notionnel par jambe et par côté (frais + spread + glissement), déclarée en spec
    require_coint: bool = True


def simulate_pair(a_open, a_close, b_open, b_close, p: PairParams) -> list[dict]:
    """Renvoie la liste des trades {entry_i, exit_i, side, r, reason}. Prix strictement positifs. Positions nominales : +1 de a, -beta de b (en log-notionnel)."""
    la, lb = np.log(np.asarray(a_close, float)), np.log(np.asarray(b_close, float))
    oa, ob = np.log(np.asarray(a_open, float)), np.log(np.asarray(b_open, float))
    n = len(la)
    kf = Kalman(p.delta, p.obs_var, 1.0)
    ok = False
    var_e = None; lam = 0.5 ** (1.0 / p.sigma_halflife)
    trades: list[dict] = []
    pos = None       # dict(side, entry_i, beta, sigma, ea, eb)
    pending = None   # ('enter', side) | ('exit', reason) à exécuter à l'ouverture de i+1
    for i in range(n):
        # exécution des ordres décidés à la clôture précédente, à l'ouverture de i
        if pending is not None:
            kind, arg = pending; pending = None
            if kind == "enter" and pos is None:
                pos = {"side": arg[0], "entry_i": i, "beta": arg[1], "sigma": arg[2], "ea": oa[i], "eb": ob[i]}
            elif kind == "exit" and pos is not None:
                trades.append(_close(pos, i, oa[i], ob[i], arg, p))
                pos = None
        e, _ = kf.step(la[i], lb[i])
        sig_prior = None if var_e is None else float(np.sqrt(var_e))   # écart-type connu AVANT cette innovation
        var_e = e * e if var_e is None else lam * var_e + (1.0 - lam) * e * e
        if i < p.warmup or sig_prior is None or sig_prior <= 0:
            continue
        if p.require_coint and ((i - p.warmup) % p.coint_every == 0):
            lo = max(0, i - p.coint_window + 1)
            ok = engle_granger(la[lo:i + 1], lb[lo:i + 1])["cointegrated"]
        elif not p.require_coint:
            ok = True
        sigma = sig_prior; z = e / sigma
        if pos is not None:
            held = i - pos["entry_i"]
            # side=+1 : long spread (a - beta b), entré quand z <= -z_entry ; sortie quand z remonte à >= z_exit
            if pos["side"] == +1 and z >= p.z_exit:
                pending = ("exit", "target")
            elif pos["side"] == -1 and z <= -p.z_exit:
                pending = ("exit", "target")
            if abs(z) >= p.z_stop and (z * pos["side"]) < 0:
                pending = ("exit", "stop")
            elif not ok:
                pending = ("exit", "coint_break")
            elif held >= p.max_hold:
                pending = ("exit", "time")
        elif ok and i + 1 < n and abs(z) >= p.z_entry and abs(z) < p.z_stop:
            side = +1 if z < 0 else -1
            beta = float(kf.theta[1])
            if beta > 0:
                pending = ("enter", (side, beta, sigma))
    if pos is not None:                       # position encore ouverte en fin de données : clôturée à la dernière clôture, marquée "end"
        trades.append(_close(pos, n - 1, la[-1], lb[-1], "end", p))
    return trades


def _close(pos: dict, i: int, xa: float, xb: float, reason: str, p: PairParams) -> dict:
    s, beta = pos["side"], pos["beta"]
    pnl = s * ((xa - pos["ea"]) - beta * (xb - pos["eb"]))      # log-rendement du spread long a / short beta*b
    cost = 2 * p.cost_per_leg * (1.0 + beta)                    # 2 jambes x (entrée+sortie) en fraction de notionnel
    risk = (p.z_stop - p.z_entry) * pos["sigma"]                 # distance de stop en unités de spread
    return {"entry_i": pos["entry_i"], "exit_i": i, "side": s, "reason": reason, "beta": beta,
            "gross": float(pnl), "cost": float(cost), "r": float((pnl - cost) / risk)}
