"""Scénarios FTMO par Monte-Carlo. CONDITIONNEL : on suppose une espérance par
trade (en R) ; ce n'est pas une estimation de l'avantage réel de NEXUS.

Limites déclarées : pas de flottant intra-trade (le flottant ne peut qu'aggraver
les violations de perte journalière), une seule journée Prague = un bloc de
trades, trades indépendants (pas de corrélation ni de dépendance de régime),
risque fixe en % de l'equity courante."""
from __future__ import annotations

import numpy as np

from .ftmo import FtmoRules


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def simulate(sampler, risk_pct: float, trades_per_day: float, rules: FtmoRules = FtmoRules(),
             max_days: int = 60, n_sims: int = 5000, seed: int = 0, trade_days_per_week: int = 5):
    """sampler(rng, n) -> tableau de n résultats en R NETS de coûts.
    Retourne dict : proportions + IC de Wilson (erreur d'échantillonnage MC seule)."""
    rng = np.random.default_rng(seed)
    ib = rules.initial_balance
    target = ib * (1 + rules.profit_target_pct / 100)
    floor = ib * (1 - rules.max_total_loss_pct / 100)
    dlim = rules.max_daily_loss_pct / 100 * ib
    res = {"passed": 0, "failed_daily_loss": 0, "failed_max_loss": 0, "incomplete": 0}
    pass_days, best_days = [], []
    for _ in range(n_sims):
        bal, status, days_traded = ib, "incomplete", 0
        best = 0.0
        for day in range(1, max_days + 1):
            if (day - 1) % 7 >= trade_days_per_week:
                continue
            ref = bal
            n = rng.poisson(trades_per_day)
            if n:
                days_traded += 1
            for r in sampler(rng, n):
                bal += bal * risk_pct / 100 * r
                if ref - bal >= dlim:
                    status = "failed_daily_loss"
                    break
                if bal <= floor:
                    status = "failed_max_loss"
                    break
            else:
                best = max(best, (bal - ref) / ib * 100)
                if bal >= target and days_traded >= rules.min_trading_days:
                    status = "passed"
                    pass_days.append(day)
                    break
                continue
            break
        best_days.append(best)
        res[status] += 1
    out = {k: {"p": v / n_sims, "ci95": wilson(v, n_sims)} for k, v in res.items()}
    out["median_days_to_pass"] = float(np.median(pass_days)) if pass_days else None
    out["p_any_day_gain_ge_3pct"] = float(np.mean(np.array(best_days) >= 3.0))
    return out


def bernoulli_sampler(p_win: float, win_r: float, cost_r: float = 0.05):
    def f(rng, n):
        return np.where(rng.random(n) < p_win, win_r, -1.0) - cost_r
    return f


def bootstrap_sampler(r_values):
    r = np.asarray(r_values, float)

    def f(rng, n):
        return rng.choice(r, size=n, replace=True)
    return f


def expectancy(p_win, win_r, cost_r):
    return p_win * win_r - (1 - p_win) - cost_r
