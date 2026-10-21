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
