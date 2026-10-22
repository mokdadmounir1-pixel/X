"""Simulateur de challenge FTMO 2-Step par bootstrap stationnaire [SYNTHETIQUE/SIMULE].

Entree: rendements journaliers BRUTS de la strategie. Le gouverneur est applique
dynamiquement dans la simulation. Limites: jours seulement (pas d'intra-jour),
regles tierces non verifiees, dependance temporelle approchee par blocs.
"""
from __future__ import annotations

import random
from collections import Counter

from .rules import FtmoRules, Governor


def _path(pool: list[float], n: int, mean_block: int, rng: random.Random):
    i = rng.randrange(len(pool))
    p = 1.0 / mean_block
    for _ in range(n):
        yield pool[i]
        i = rng.randrange(len(pool)) if rng.random() < p else (i + 1) % len(pool)


def run_phase(pool, rules: FtmoRules, gov: Governor, target: float,
              rng: random.Random, mean_block: int = 10, max_days: int = 504,
              scale: float = 1.0) -> str:
    """pool: floats (rendement jour) ou tuples (rendement, pire point intra-jour <= 0).
    `scale` multiplie le risque (taille de position); le gouverneur s'applique par-dessus."""
    eq = 1.0  # en fraction du solde initial
    for day, item in enumerate(_path(pool, max_days, mean_block, rng), start=1):
        r, worst = item if isinstance(item, tuple) else (item, min(item, 0.0))
        s = gov.scale(eq) * scale
        eq += s * r
        if s * worst <= -rules.max_daily_loss or (eq - s * r) + s * worst <= 1 - rules.max_loss:
            return "FAIL_DAILY" if s * worst <= -rules.max_daily_loss else "FAIL_MAX"
        if eq <= 1 - rules.max_loss:
            return "FAIL_MAX"
        if eq >= 1 + target and day >= rules.min_days:
            return "PASS"
    return "TIMEOUT"   # inclut l'etat 'gele' par le gouverneur


def two_step(pool, rules=FtmoRules(), gov=Governor(), sims=5000, seed=0,
             mean_block=10, max_days=504, scale=1.0) -> dict:
    rng = random.Random(seed)
    c1 = Counter(run_phase(pool, rules, gov, rules.target_p1, rng, mean_block, max_days, scale)
                 for _ in range(sims))
    c2 = Counter(run_phase(pool, rules, gov, rules.target_p2, rng, mean_block, max_days, scale)
                 for _ in range(sims))
    f = lambda c, k: c[k] / sims
    p1, p2 = f(c1, "PASS"), f(c2, "PASS")
    return {"phase1": {k: f(c1, k) for k in ("PASS", "FAIL_DAILY", "FAIL_MAX", "TIMEOUT")},
            "phase2": {k: f(c2, k) for k in ("PASS", "FAIL_DAILY", "FAIL_MAX", "TIMEOUT")},
            "pass_both": p1 * p2, "sims": sims, "max_days": max_days}
