"""Dépendance de queue empirique entre deux séries de rendements (stratégie/outil n°11 : défense contre la contagion).

lambda_bas(q) = P(Y <= q-quantile | X <= q-quantile) ; sous indépendance, lambda = q. Le RATIO lambda/q mesure l'excès de dépendance dans les queues. Les seuils de « contagion » ne sont pas fixés ici :
c'est une mesure à comparer à q, pas un interrupteur.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def tail_dependence(x, y, q: float = 0.05) -> dict:
    d = pd.concat([pd.Series(np.asarray(x, float)), pd.Series(np.asarray(y, float))], axis=1).dropna(); u = d.rank(pct=True)
    if len(d) < 200:
        return {"status": "donnees_insuffisantes"}
    lo = float(((u[0] <= q) & (u[1] <= q)).sum() / max((u[0] <= q).sum(), 1)); hi = float(((u[0] >= 1 - q) & (u[1] >= 1 - q)).sum() / max((u[0] >= 1 - q).sum(), 1))
    return {"status": "ok", "q": q, "n": int(len(d)), "lower": lo, "upper": hi, "lower_ratio": lo / q, "upper_ratio": hi / q, "corr": float(d[0].corr(d[1]))}
