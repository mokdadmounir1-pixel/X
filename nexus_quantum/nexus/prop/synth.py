"""Generateurs [SYNTHETIQUE] pour tester la chaine, jamais pour affirmer un edge de marche."""
from __future__ import annotations

import random


def make_prices(n_assets=8, n_days=3780, vol=0.01, phi=0.0, seed=0) -> dict[str, list[float]]:
    """Rendements AR(1): r_t = phi*r_{t-1} + eps. phi=0 => marche de Gauss sans edge."""
    rng = random.Random(seed)
    out = {}
    for a in range(n_assets):
        r_prev, p, ps = 0.0, 100.0, [100.0]
        for _ in range(n_days - 1):
            r = phi * r_prev + rng.gauss(0, vol)
            p *= (1 + r); ps.append(p); r_prev = r
        out[f"SYN{a}"] = ps
    return out
