"""Statistiques robustes : espérance, PF, Monte Carlo par blocs, séries de pertes, Deflated Sharpe."""
from __future__ import annotations
import math
from statistics import NormalDist
import numpy as np

ND = NormalDist()


def expectancy(r) -> float:
    r = np.asarray(r, float)
    return float(r.mean()) if len(r) else 0.0


def profit_factor(r) -> float:
    r = np.asarray(r, float)
    g, l = r[r > 0].sum(), -r[r < 0].sum()
    return float(g / l) if l > 0 else (float("inf") if g > 0 else 0.0)


def top_k_share(r, k=3) -> float:
    r = np.asarray(r, float)
    tot = r.sum()
    if tot <= 0:
        return 1.0
    return float(np.sort(r)[::-1][:k].sum() / tot)


def max_losing_streak(r) -> int:
    best = cur = 0
    for x in np.asarray(r, float):
        cur = cur + 1 if x < 0 else 0
        best = max(best, cur)
    return best


def block_indices(n, length, block, rng, paths):
    """Indices de rééchantillonnage par blocs circulaires (préserve les regroupements de pertes)."""
    nb = int(math.ceil(length / block))
    starts = rng.integers(0, n, size=(paths, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    return idx.reshape(paths, -1)[:, :length]


def mc_paths(r, risk_pct, length=None, paths=2000, block=3, seed=0):
    """Équité (capital = 1) de chemins rééchantillonnés ; additif en risque fixe (pas de composition)."""
    r = np.asarray(r, float)
    if len(r) == 0:
        return np.ones((paths, 1)), np.zeros(paths), np.zeros(paths)
    rng = np.random.default_rng(seed)
    length = length or len(r)
    idx = block_indices(len(r), length, min(block, len(r)), rng, paths)
    x = r[idx] * risk_pct / 100.0
    eq = 1.0 + np.cumsum(x, axis=1)
    peak = np.maximum.accumulate(np.maximum(eq, 1.0), axis=1)
    dd = (peak - eq).max(axis=1)
    streak = np.zeros(paths)
    cur = np.zeros(paths)
    best = np.zeros(paths)
    for k in range(x.shape[1]):
        cur = np.where(x[:, k] < 0, cur + 1, 0)
        best = np.maximum(best, cur)
    return eq, dd, best


def sharpe_stats(r):
    r = np.asarray(r, float)
    n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return 0.0, 0.0, 3.0, n
    sr = r.mean() / r.std(ddof=1)
    z = (r - r.mean()) / r.std(ddof=1)
    return float(sr), float((z ** 3).mean()), float((z ** 4).mean()), n


def deflated_sharpe(r, trial_srs, n_trials) -> float:
    """Probabilité que le vrai Sharpe (par trade) > 0 après correction du nombre d'essais (Bailey & LdP)."""
    sr, sk, ku, n = sharpe_stats(r)
    if n < 10:
        return 0.0
    v = float(np.var(trial_srs)) if len(trial_srs) > 1 else 0.0
    g = 0.5772156649
    sr0 = math.sqrt(v) * ((1 - g) * ND.inv_cdf(1 - 1 / max(n_trials, 2)) + g * ND.inv_cdf(1 - 1 / (max(n_trials, 2) * math.e)))
    den = math.sqrt(max(1e-9, 1 - sk * sr + (ku - 1) / 4 * sr * sr))
    return float(ND.cdf((sr - sr0) * math.sqrt(n - 1) / den))


def stationary_indices(n, length, mean_block, rng, paths):
    """Indices d'un bootstrap stationnaire (Politis-Romano) : blocs de longueur géométrique, circulaire."""
    p = 1.0 / max(1.0, mean_block)
    idx = np.empty((paths, length), np.int64)
    idx[:, 0] = rng.integers(0, n, paths)
    new = rng.random((paths, length)) < p
    jump = rng.integers(0, n, (paths, length))
    for k in range(1, length):
        idx[:, k] = np.where(new[:, k], jump[:, k], (idx[:, k - 1] + 1) % n)
    return idx


def reality_check(daily: np.ndarray, B=2000, mean_block=5, seed=0):
    """White (2000) Reality Check sur une matrice (jours × stratégies) de rendements quotidiens en R (benchmark 0) :
    p-value de H0 « aucune stratégie n'a une espérance > 0 », en tenant compte du fait qu'on retient la meilleure."""
    d = np.asarray(daily, float)
    n, k = d.shape
    if n < 30 or k == 0:
        return {"p": None, "best": None, "n_days": int(n)}
    mu = d.mean(0)
    stat = float(np.sqrt(n) * mu.max())
    rng = np.random.default_rng(seed)
    idx = stationary_indices(n, n, mean_block, rng, B)
    boot = np.sqrt(n) * (d[idx].mean(1) - mu).max(1)
    return {"p": round(float((1 + (boot >= stat).sum()) / (B + 1)), 4), "best": int(mu.argmax()),
            "best_mean_R_per_day": round(float(mu.max()), 4), "n_days": int(n)}
