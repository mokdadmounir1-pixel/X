"""Economie du capital: point mort et risque de ruine. Sorties [SYNTHETIQUE]/[HYPOTHESE]."""
from __future__ import annotations

import random


def required_gross_edge_per_trade(cost_rt: float, trades_per_month: float,
                                  fixed_monthly: float) -> float:
    """Edge brut moyen (monnaie/trade) pour un resultat mensuel net nul."""
    if trades_per_month <= 0:
        raise ValueError("trades_per_month > 0")
    return cost_rt + fixed_monthly / trades_per_month


def ruin_probability_mc(p_win: float, rr: float, risk_frac: float, ruin_frac: float,
                        n_trades: int, sims: int = 20000, seed: int = 0) -> float:
    """P(equity <= ruin_frac * capital initial) en n_trades; risque fixe en fraction
    de l'equity courant; gain = rr * risque. Hypothese iid: sous-estime la ruine reelle."""
    rng = random.Random(seed)
    ruined = 0
    for _ in range(sims):
        eq = 1.0
        for _ in range(n_trades):
            eq *= (1 + risk_frac * rr) if rng.random() < p_win else (1 - risk_frac)
            if eq <= ruin_frac:
                ruined += 1
                break
    return ruined / sims
