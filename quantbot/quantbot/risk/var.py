"""VaR / Expected Shortfall paramétriques et historiques, et Kelly fractionnaire. Fonctions pures, mesures descriptives (aucune garantie de perte maximale)."""
from __future__ import annotations

from statistics import NormalDist

import numpy as np


def parametric_var_es(returns, confidence: float = 0.95) -> dict:
    """VaR et ES gaussiens (perte positive, en unités de `returns`). La normalité est une hypothèse FAUSSE sur les rendements de marché : lire aussi l'historique."""
    r = np.asarray(returns, float)
    if len(r) < 30:
        return {"var": float("nan"), "es": float("nan")}
    mu, sd = float(r.mean()), float(r.std(ddof=1)); nd = NormalDist(); z = nd.inv_cdf(confidence)
    return {"var": -(mu - z * sd), "es": -(mu - sd * nd.pdf(z) / (1.0 - confidence))}


def historical_var_es(returns, confidence: float = 0.95) -> dict:
    r = np.sort(np.asarray(returns, float))
    if len(r) < 30:
        return {"var": float("nan"), "es": float("nan")}
    k = max(1, int(np.floor((1.0 - confidence) * len(r))))
    return {"var": float(-r[k - 1]), "es": float(-r[:k].mean())}


def fractional_kelly(win_rate: float, payoff: float, fraction: float = 0.3, cap: float = 1.0) -> float:
    """f* = p - (1-p)/b, multiplié par `fraction`, borné à [0, cap]. payoff = gain moyen / perte moyenne. Un Kelly estimé sur peu de trades est instable : utiliser une borne basse (voir risk/active.py)."""
    if payoff <= 0:
        return 0.0
    return float(min(cap, max(0.0, fraction * (win_rate - (1.0 - win_rate) / payoff))))
