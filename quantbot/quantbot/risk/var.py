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


def gpd_fit_pwm(excesses) -> tuple[float, float]:
    """Loi de Pareto généralisée (xi forme, beta échelle) par moments pondérés (Hosking & Wallis 1987). Robuste sur petits échantillons ; xi < 0,5 requis pour la validité."""
    x = np.sort(np.asarray(excesses, float)); n = len(x)
    if n < 20:
        raise ValueError("au moins 20 excès pour ajuster une GPD")
    a0 = x.mean(); a1 = float(np.mean(x * (1.0 - (np.arange(1, n + 1) - 0.35) / n)))          # estimateur PWM a1 = E[X(1-F)]
    xi = 2.0 - a0 / (a0 - 2.0 * a1); beta = 2.0 * a0 * a1 / (a0 - 2.0 * a1)
    return float(xi), float(beta)


def evt_var_es(returns, confidence: float = 0.99, threshold_q: float = 0.95) -> dict:
    """VaR et ES par Peaks-Over-Threshold (EVT) sur les PERTES : seuil u = quantile `threshold_q`, queue GPD ; formules de McNeil-Frey :
    VaR_p = u + (beta/xi)((n/Nu x (1-p))^-xi - 1) ; ES_p = VaR_p/(1-xi) + (beta - xi u)/(1-xi). Renvoie aussi xi (indice de queue : plus grand = queue plus lourde)."""
    r = np.asarray(returns, float); losses = -r[r < 0]
    if len(losses) < 100:
        return {"status": "donnees_insuffisantes"}
    u = float(np.quantile(losses, threshold_q)); exc = losses[losses > u] - u
    if len(exc) < 20:
        return {"status": "queue_trop_courte"}
    xi, beta = gpd_fit_pwm(exc); n, nu = len(losses), len(exc)
    if not 0.0 < beta or xi >= 1.0:
        return {"status": "ajustement_invalide", "xi": xi, "beta": beta}
    q = (n / nu) * (1.0 - confidence)
    var = u + (beta / xi) * (q ** (-xi) - 1.0) if abs(xi) > 1e-9 else u - beta * np.log(q)
    es = var / (1.0 - xi) + (beta - xi * u) / (1.0 - xi)
    return {"status": "ok", "var": float(var), "es": float(es), "xi": xi, "beta": beta, "threshold": u, "n_excess": nu}
