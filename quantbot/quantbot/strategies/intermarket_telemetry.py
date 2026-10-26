"""Télémétrie inter-marchés : lead-lag mesuré entre l'or et des séries de référence (EURUSD, USTEC, et DXY / argent / cuivre / taux réels SI exportés).

À l'échelle des BARRES (M15) uniquement : l'avance de quelques millisecondes décrite pour le HFT n'est pas observable ici (pas de ticks synchronisés multi-marchés)
et, mesurée sur nos données, l'avance à une barre est statistiquement nulle (voir `lead_lag`). Le module sert à MESURER avant d'utiliser ; il ne suppose aucun lead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def lead_lag(gold_close: pd.Series, ref_close: pd.Series, max_lag: int = 4) -> pd.DataFrame:
    """Corrélations corr(r_or[t], r_ref[t - lag]) pour lag = 0..max_lag (lag 0 = simultané, lag >= 1 = la référence MÈNE), avec erreur-type 1/sqrt(N) et t-stat."""
    d = pd.concat([np.log(gold_close).diff(), np.log(ref_close).diff()], axis=1, join="inner").dropna(); d.columns = ["g", "x"]; n = len(d)
    rows = [{"lag": l, "corr": float(d.g.corr(d.x.shift(l))), "t": float(d.g.corr(d.x.shift(l)) * np.sqrt(n))} for l in range(max_lag + 1)]
    return pd.DataFrame(rows).assign(n=n)


def telemetry_score(ref_returns: np.ndarray, gold_returns_scale: np.ndarray, beta_lag1: float, cap: float = 2.0) -> np.ndarray:
    """Score signé dans [-1, 1] : prévision linéaire de l'or par le rendement RETARDÉ de la référence (bêta mesuré en recherche), en unités d'écart-type du rendement de l'or, borné par tanh.
    N'a de sens que si `lead_lag` a montré un lag >= 1 significatif ET économiquement utile ; sinon ne pas l'utiliser."""
    return np.tanh(beta_lag1 * np.asarray(ref_returns, float) / np.maximum(np.asarray(gold_returns_scale, float), 1e-12) / cap)
