"""Les 9 portes anti-surapprentissage + DSR. Chaque porte retourne (ok, valeur, seuil)."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from . import stats as st


# Portes ÉLIMINATOIRES (un échec = pas d'edge utilisable, quelle que soit la performance) vs STATISTIQUES (qualité de l'estimation).
GATE_CLASS = {"g1_n_oos": "éliminatoire", "g2_expectancy": "statistique", "g3_profit_factor": "statistique",
              "g4_null": "éliminatoire", "g5_costs_x2": "éliminatoire", "g6_monte_carlo_p5": "éliminatoire",
              "g7_top3_share": "statistique", "g8_plateau": "statistique", "g9_loss_streak": "éliminatoire"}


@dataclass
class GateCfg:
    min_trades: int = 60
    min_exp: float = 0.30
    min_pf: float = 1.30
    null_alpha: float = 0.10
    top3_max: float = 0.50
    plateau_frac: float = 0.75
    risk_pct: float = 0.5
    dd_frac: float = 0.60        # marge : DD95 ≤ 60 % de la perte max autorisée
    mc_paths: int = 2000
    min_years: float = 3.0
    dsr_min: float = 0.5


def cheap_gates(r: np.ndarray, r_cost2: np.ndarray | None, nb_exp: list[float] | None, cfg: GateCfg,
                max_loss_pct: float, trades_per_year: float):
    g = {}
    n = len(r)
    g["g1_n_oos"] = (n >= cfg.min_trades, n, cfg.min_trades)
    e = st.expectancy(r); g["g2_expectancy"] = (e >= cfg.min_exp, round(e, 3), cfg.min_exp)
    pf = st.profit_factor(r); g["g3_profit_factor"] = (pf > cfg.min_pf, round(pf, 2), cfg.min_pf)
    e2 = st.expectancy(r_cost2) if r_cost2 is not None and len(r_cost2) else float("nan")
    g["g5_costs_x2"] = (bool(e2 > 0), None if np.isnan(e2) else round(e2, 3), 0.0)
    eq, dd, streak = st.mc_paths(r, cfg.risk_pct, length=max(10, int(round(trades_per_year))), paths=cfg.mc_paths)
    eq_full, _, _ = st.mc_paths(r, cfg.risk_pct, length=max(10, n), paths=cfg.mc_paths, seed=1)
    p5 = float(np.percentile(eq_full[:, -1], 5)) if len(r) else 0.0
    g["g6_monte_carlo_p5"] = (p5 > 1.0, round(p5, 4), 1.0)
    t3 = st.top_k_share(r, 3); g["g7_top3_share"] = (t3 < cfg.top3_max, round(t3, 3), cfg.top3_max)
    if nb_exp:
        frac = float(np.mean(np.array(nb_exp) > 0))
        g["g8_plateau"] = (frac >= cfg.plateau_frac and float(np.mean(nb_exp)) > 0, round(frac, 2), cfg.plateau_frac)
    else:
        g["g8_plateau"] = (False, None, cfg.plateau_frac)
    dd95 = float(np.percentile(dd, 95)) * 100; s95 = float(np.percentile(streak, 95))
    lim = cfg.dd_frac * max_loss_pct
    g["g9_loss_streak"] = (dd95 <= lim and s95 * cfg.risk_pct <= lim, {"dd95_pct": round(dd95, 2), "streak95": s95},
                           {"dd_max_pct": lim})
    return g


def null_gate(obs: float, null: np.ndarray, n_tests: int, cfg: GateCfg):
    B = len(null)
    p = (1 + int((null >= obs).sum())) / (1 + B)
    alpha = 1 - (1 - cfg.null_alpha) ** (1 / max(n_tests, 1))    # correction de Šidák
    return (p < alpha, round(p, 4), round(alpha, 4))


def verdict(g: dict, dsr_p: float, years: float, cfg: GateCfg, exp: float):
    fails = [k for k, v in g.items() if not v[0]]
    elim = [k for k in fails if GATE_CLASS.get(k) == "éliminatoire"
            and not (isinstance(g[k][1], str) and g[k][1].startswith("non évalué"))]
    if not fails and dsr_p >= cfg.dsr_min:
        if years < cfg.min_years:
            return "WATCH", f"plafonné : {years:.1f} an(s) de données < {cfg.min_years:.0f} requis"
        return "PASS", ""
    why = "échoue : " + ",".join(fails + (["dsr"] if dsr_p < cfg.dsr_min else []))
    if elim:
        why += " | ÉLIMINATOIRE(S) : " + ",".join(elim)
    if exp > 0 and not elim and len(fails) + (dsr_p < cfg.dsr_min) <= 2:
        return "WATCH", why
    return "FAIL", why
