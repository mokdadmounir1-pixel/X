"""Portes de validation sur les résultats en R. Seuils PRÉENREGISTRÉS : changer un seuil change le hachage de la spec.

Éliminatoires : un échec = pas d'edge utilisable, quelle que soit la performance.
Statistiques  : qualité de l'estimation ; deux échecs au plus autorisent un simple WATCH.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

from . import stats as st


@dataclass(frozen=True)
class GateCfg:
    min_trades: int = 60
    min_expectancy: float = 0.15  # R net de coûts
    min_profit_factor: float = 1.2
    null_alpha: float = 0.10  # corrigé de Šidák sur le nombre d'essais
    top3_max: float = 0.50
    min_positive_folds: float = 0.50
    mc_paths: int = 2000
    dd_frac: float = 0.60  # DD95 <= 60 % de la perte max autorisée
    dsr_min: float = 0.50
    min_years: float = 2.0
    base_B: int = 999

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Gate:
    name: str
    ok: bool
    value: object = None
    threshold: object = None
    eliminatory: bool = False

    def to_dict(self) -> dict:
        v = self.value
        if isinstance(v, float) and not np.isfinite(v):
            v = str(v)
        return {"name": self.name, "ok": bool(self.ok), "value": v, "threshold": self.threshold,
                "eliminatory": self.eliminatory}


def run_gates(r, r_cost2, fold_expectancies: list, n_trials: int, var_sr_trials: float, years: float,
              risk_pct: float, max_loss_pct: float, cfg: GateCfg) -> list[Gate]:
    r = np.asarray(r, float)
    n = r.size
    gates: list[Gate] = []
    gates.append(Gate("n_trades", n >= cfg.min_trades, n, cfg.min_trades, True))
    e = st.expectancy(r)
    gates.append(Gate("expectancy", e >= cfg.min_expectancy, round(e, 4), cfg.min_expectancy))
    pf = st.profit_factor(r)
    gates.append(Gate("profit_factor", pf >= cfg.min_profit_factor, round(pf, 3), cfg.min_profit_factor))

    alpha = st.sidak_alpha(cfg.null_alpha, n_trials)
    res = st.null_resolution(alpha, base_B=cfg.base_B)
    if res["evaluable"] and n >= 5:
        p = st.sign_flip_pvalue(r, B=res["B"])
        gates.append(Gate("null_test", p < alpha, round(p, 5), round(alpha, 5), True))
    else:
        gates.append(Gate("null_test", False, "non évaluable (trop d'essais ou trop peu de trades)", round(alpha, 6), True))

    e2 = st.expectancy(r_cost2) if r_cost2 is not None and len(r_cost2) else float("nan")
    gates.append(Gate("costs_x2", bool(e2 > 0), None if np.isnan(e2) else round(e2, 4), 0.0, True))

    eq_full, _, _ = st.mc_paths(r, risk_pct, length=max(10, n), paths=cfg.mc_paths, seed=1)
    p5 = float(np.percentile(eq_full[:, -1], 5)) if n else 0.0
    gates.append(Gate("monte_carlo_p5", p5 > 1.0, round(p5, 4), 1.0, True))

    gates.append(Gate("top3_share", st.top_k_share(r, 3) < cfg.top3_max, round(st.top_k_share(r, 3), 3), cfg.top3_max))

    ratio = float(np.mean([x > 0 for x in fold_expectancies])) if fold_expectancies else 0.0
    gates.append(Gate("folds_positive", ratio >= cfg.min_positive_folds, round(ratio, 2), cfg.min_positive_folds))

    trades_per_year = n / years if years > 0 else float(n)
    _, dd, streak = st.mc_paths(r, risk_pct, length=max(10, int(round(trades_per_year))), paths=cfg.mc_paths)
    dd95, s95 = float(np.percentile(dd, 95)) * 100, float(np.percentile(streak, 95))
    lim = cfg.dd_frac * max_loss_pct
    gates.append(Gate("risk_envelope", dd95 <= lim and s95 * risk_pct <= lim,
                      {"dd95_pct": round(dd95, 2), "streak95": s95}, {"max_pct": round(lim, 2)}, True))

    dsr = st.deflated_sharpe(r, n_trials, var_sr_trials)
    gates.append(Gate("deflated_sharpe", dsr >= cfg.dsr_min, round(dsr, 4), cfg.dsr_min, True))
    return gates


def verdict(gates: list[Gate], expectancy: float, years: float, cfg: GateCfg) -> tuple[str, str]:
    fails = [g for g in gates if not g.ok]
    elim = [g.name for g in fails if g.eliminatory]
    if not fails:
        if years < cfg.min_years:
            return "WATCH", f"plafonné : {years:.1f} an(s) de données < {cfg.min_years:.0f} requis"
        return "PASS", ""
    why = "échoue : " + ",".join(g.name for g in fails)
    if elim:
        why += " | éliminatoire(s) : " + ",".join(elim)
    if expectancy > 0 and not elim and len(fails) <= 2:
        return "WATCH", why
    return "FAIL", why
