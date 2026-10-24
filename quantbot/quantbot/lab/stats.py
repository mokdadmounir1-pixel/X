"""Statistiques de validation sur des résultats en R (multiples du risque).

Référence : Bailey & López de Prado (PSR 2012, DSR 2014), Politis & Romano (bootstrap
stationnaire 1994), White (Reality Check 2000). Réécrit pour ce projet, sans dépendance.
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Optional

import numpy as np

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def expectancy(r) -> float:
    r = np.asarray(r, float)
    return float(r.mean()) if r.size else 0.0


def profit_factor(r) -> float:
    r = np.asarray(r, float)
    gain, loss = r[r > 0].sum(), -r[r < 0].sum()
    return float(gain / loss) if loss > 0 else (float("inf") if gain > 0 else 0.0)


def top_k_share(r, k: int = 3) -> float:
    """Part du profit total portée par les k meilleurs trades (1.0 si profit <= 0)."""
    r = np.asarray(r, float)
    total = r.sum()
    if total <= 0:
        return 1.0
    return float(np.sort(r)[::-1][:k].sum() / total)


def sharpe_moments(r) -> tuple[float, float, float, int]:
    """(Sharpe par trade, skew, kurtosis brute [normale=3], n)."""
    r = np.asarray(r, float)
    n = r.size
    if n < 4 or r.std(ddof=1) == 0:
        return 0.0, 0.0, 3.0, n
    z = (r - r.mean()) / r.std(ddof=1)
    return float(r.mean() / r.std(ddof=1)), float((z ** 3).mean()), float((z ** 4).mean()), n


def psr(sr: float, n: int, skew: float, kurt: float, sr_benchmark: float = 0.0) -> float:
    """P(Sharpe vrai > benchmark) en tenant compte de l'asymétrie et des queues."""
    if n < 2:
        return 0.0
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom <= 0:
        return 0.0
    return float(_N.cdf((sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(denom)))


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """E[max SR] attendu sous H0 (aucun edge) après `n_trials` essais."""
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    return math.sqrt(var_sr) * ((1 - EULER_GAMMA) * _N.inv_cdf(1 - 1.0 / n_trials)
                                + EULER_GAMMA * _N.inv_cdf(1 - 1.0 / (n_trials * math.e)))


def deflated_sharpe(r, n_trials: int, var_sr_trials: float) -> float:
    """PSR contre le meilleur Sharpe attendu du hasard : sanctionne le nombre d'essais."""
    sr, skew, kurt, n = sharpe_moments(r)
    if n < 10:
        return 0.0
    return psr(sr, n, skew, kurt, expected_max_sharpe(n_trials, var_sr_trials))


def min_track_record_length(sr: float, skew: float, kurt: float, sr_benchmark: float = 0.0,
                            confidence: float = 0.95) -> float:
    """Nombre minimal d'observations pour que PSR >= confidence (inf si sr <= benchmark)."""
    if sr <= sr_benchmark:
        return math.inf
    z = _N.inv_cdf(confidence)
    return 1 + (1 - skew * sr + (kurt - 1) / 4 * sr * sr) * (z / (sr - sr_benchmark)) ** 2


def required_sample_size(effect_sr: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Observations pour détecter un Sharpe par trade `effect_sr` (test unilatéral, iid : optimiste)."""
    if effect_sr <= 0:
        raise ValueError("effect_sr doit être > 0")
    return int(math.ceil(((_N.inv_cdf(1 - alpha) + _N.inv_cdf(power)) / effect_sr) ** 2))


def block_indices(n: int, length: int, block: int, rng: np.random.Generator, paths: int) -> np.ndarray:
    """Indices de rééchantillonnage par blocs circulaires (préserve les séries de pertes)."""
    nb = int(math.ceil(length / block))
    starts = rng.integers(0, n, size=(paths, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    return idx.reshape(paths, -1)[:, :length]


def mc_paths(r, risk_pct: float, length: Optional[int] = None, paths: int = 2000, block: int = 3, seed: int = 0):
    """Monte-Carlo par blocs : (équité capital=1 [paths x length], drawdown max, plus longue série de pertes).

    Risque fixe (pas de composition) : un trade de +1R vaut +risk_pct % du capital.
    """
    r = np.asarray(r, float)
    if r.size == 0:
        return np.ones((paths, 1)), np.zeros(paths), np.zeros(paths)
    rng = np.random.default_rng(seed)
    length = length or r.size
    x = r[block_indices(r.size, length, min(block, r.size), rng, paths)] * risk_pct / 100.0
    eq = 1.0 + np.cumsum(x, axis=1)
    peak = np.maximum.accumulate(np.maximum(eq, 1.0), axis=1)
    dd = (peak - eq).max(axis=1)
    cur = np.zeros(paths)
    best = np.zeros(paths)
    for k in range(x.shape[1]):
        cur = np.where(x[:, k] < 0, cur + 1, 0)
        best = np.maximum(best, cur)
    return eq, dd, best


def sign_flip_pvalue(r, B: int = 999, block: int = 3, seed: int = 0) -> float:
    """Test nul : H0 = les résultats sont symétriques autour de 0 (aucun edge).

    Les signes sont tirés au hasard par BLOCS de trades (préserve le regroupement).
    p = (1 + #{moyenne_nulle >= moyenne_observée}) / (B + 1) ; plus petit p atteignable = 1/(B+1).
    """
    r = np.asarray(r, float)
    if r.size < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(r.size / block))
    signs = np.repeat(rng.choice([-1.0, 1.0], size=(B, nb)), block, axis=1)[:, : r.size]
    null = (signs * r[None, :]).mean(axis=1)
    return float((1 + int((null >= r.mean()).sum())) / (1 + B))


def sidak_alpha(alpha: float, n_tests: int) -> float:
    return 1.0 - (1.0 - alpha) ** (1.0 / max(n_tests, 1))


def null_resolution(alpha_per_test: float, margin: float = 1.25, base_B: int = 999, cap: int = 200_000) -> dict:
    """B tel que le plus petit p (1/(B+1)) reste sous alpha avec marge ; sinon test non évaluable."""
    need = int(math.ceil(margin / alpha_per_test)) - 1
    B = max(base_B, need)
    return {"B": min(B, cap), "evaluable": B <= cap, "alpha_per_test": alpha_per_test}


def stationary_indices(n: int, length: int, mean_block: float, rng: np.random.Generator, paths: int) -> np.ndarray:
    """Bootstrap stationnaire (Politis-Romano) : blocs de longueur géométrique, circulaire."""
    p = 1.0 / max(1.0, mean_block)
    idx = np.empty((paths, length), np.int64)
    idx[:, 0] = rng.integers(0, n, paths)
    new = rng.random((paths, length)) < p
    jump = rng.integers(0, n, (paths, length))
    for k in range(1, length):
        idx[:, k] = np.where(new[:, k], jump[:, k], (idx[:, k - 1] + 1) % n)
    return idx


def reality_check(daily, B: int = 2000, mean_block: float = 5, seed: int = 0) -> dict:
    """White (2000) : H0 « aucune stratégie n'a d'espérance > 0 » sur une matrice jours x stratégies,
    en tenant compte du fait qu'on retient la meilleure."""
    d = np.asarray(daily, float)
    if d.ndim != 2 or d.shape[0] < 30 or d.shape[1] == 0:
        return {"p": None, "n_days": int(d.shape[0]) if d.ndim == 2 else 0}
    n = d.shape[0]
    mu = d.mean(0)
    stat = float(math.sqrt(n) * mu.max())
    rng = np.random.default_rng(seed)
    idx = stationary_indices(n, n, mean_block, rng, B)
    boot = math.sqrt(n) * (d[idx].mean(1) - mu).max(1)
    return {"p": float((1 + (boot >= stat).sum()) / (B + 1)), "best": int(mu.argmax()), "n_days": int(n)}
