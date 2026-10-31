"""Formules de référence des deux candidats « actions » cités par l'utilisateur (Attention Factors : arbitrage statistique ; ORB sur actions à volume inhabituel).

Ce sont des OUTILS DE CALCUL purs, testés : aucune stratégie n'est exécutée ici. Les stratégies elles-mêmes exigent des données que quantbot ne possède pas
(les 500 plus grosses actions américaines avec facteurs ; barres de 5 minutes d'actions avec volume réel d'ouverture) : voir le catalogue.
Les chiffres publiés (Sharpe 2,28 ; 41,6 % annualisé) sont des simulations d'auteurs, non reproduites ici.
"""
from __future__ import annotations

import numpy as np

TURNOVER_COST = 0.0005      # 5 points de base par unité de rotation (hypothèse de l'article)
SHORT_COST = 0.0001         # 1 point de base par jour sur l'exposition vendeuse


def portfolio_cost(w, w_prev, turnover_cost: float = TURNOVER_COST, short_cost: float = SHORT_COST) -> float:
    """Coût_t = c_rot x SOMME|w_t - w_{t-1}| + c_vente x SOMME max(-w_t, 0). L'impact de marché n'y figure PAS (limite connue de la formule)."""
    w, w_prev = np.asarray(w, float), np.asarray(w_prev, float)
    return float(turnover_cost * np.abs(w - w_prev).sum() + short_cost * np.maximum(-w, 0.0).sum())


def normalize_gross(w) -> np.ndarray:
    """Impose l'exposition brute SOMME|w_i| = 1 (vecteur nul inchangé)."""
    w = np.asarray(w, float); g = np.abs(w).sum()
    return w / g if g > 0 else w


def residual_return(r, beta_prev, factors) -> float:
    """Résidu = r_i - SOMME_k beta_{i,k,t-1} x f_{k,t} : ce qui dépasse la composante commune (un résidu négatif n'est pas une preuve de sous-évaluation)."""
    return float(r - np.dot(np.asarray(beta_prev, float), np.asarray(factors, float)))


def rvol(v5_today: float, v5_history) -> float:
    """Volume relatif à l'ouverture : V(9:30-9:35) aujourd'hui / moyenne des mêmes 5 minutes sur les 14 séances précédentes. NaN si l'historique est incomplet."""
    h = np.asarray(v5_history, float)
    if len(h) != 14 or not np.isfinite(h).all() or h.mean() <= 0:
        return float("nan")
    return float(v5_today / h.mean())


def stock_in_play(open_price: float, avg_volume_14: float, atr_14: float, open_volume: float, avg_open_volume_14: float, min_price: float = 5.0, min_volume: float = 1_000_000, min_atr: float = 0.50) -> bool:
    """Filtres de l'ORB « actions en jeu » : ouverture > 5 $, volume moyen 14 séances >= 1 M d'actions, ATR 14 séances > 0,50 $, volume d'ouverture >= sa moyenne."""
    return bool(open_price > min_price and avg_volume_14 >= min_volume and atr_14 > min_atr and open_volume >= avg_open_volume_14)


def top_by_rvol(rvols: dict, n: int = 20) -> list:
    """Les `n` titres de RVOL le plus élevé (NaN écartés ; égalité départagée par le nom pour rester déterministe)."""
    ok = [(k, v) for k, v in rvols.items() if np.isfinite(v)]
    return [k for k, _ in sorted(ok, key=lambda kv: (-kv[1], kv[0]))[:n]]


def orb_stop_distance(atr_14: float, frac: float = 0.10) -> float:
    """Distance du stop depuis l'entrée = 10 % de l'ATR 14 séances."""
    return float(frac * atr_14)


def max_quantity(risk_budget: float, stop_distance: float) -> float:
    """Quantité compatible avec le budget de perte : q <= B / d (0 si la distance est nulle ou invalide)."""
    return float(risk_budget / stop_distance) if stop_distance and stop_distance > 0 else 0.0


def cost_in_r(round_trip_cost_per_share: float, stop_distance: float) -> float:
    """Coût exprimé en unités de risque : c / d. Un stop serré rend les frais lourds (la distance baisse, pas le coût)."""
    return float(round_trip_cost_per_share / stop_distance) if stop_distance and stop_distance > 0 else float("inf")


def expectancy(p_win: float, avg_gain: float, avg_loss: float, avg_cost: float) -> float:
    """Espérance par transaction = p x gain moyen - (1-p) x perte moyenne - coût moyen (gain et perte en valeur absolue)."""
    return float(p_win * avg_gain - (1.0 - p_win) * abs(avg_loss) - avg_cost)
