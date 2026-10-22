"""Validation statistique (stdlib uniquement).

Formules: Bailey & Lopez de Prado (PSR 2012, DSR 2014), Politis & Romano (1994,
bootstrap stationnaire), Lopez de Prado (2018, purged k-fold + embargo).
Les Sharpe ici sont PAR PERIODE (non annualises) sauf mention contraire.
"""
from __future__ import annotations

import math
import random
from statistics import NormalDist

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def moments(x: list[float]) -> tuple[float, float, float, float]:
    """(moyenne, ecart-type echantillon, skew, kurtosis brute: normale=3)."""
    n = len(x)
    if n < 4:
        raise ValueError("au moins 4 observations")
    m = sum(x) / n
    d = [v - m for v in x]
    s2 = sum(v * v for v in d) / n
    if s2 == 0:
        raise ValueError("variance nulle")
    s = math.sqrt(s2)
    skew = sum(v ** 3 for v in d) / n / s ** 3
    kurt = sum(v ** 4 for v in d) / n / s ** 4
    sd = math.sqrt(s2 * n / (n - 1))
    return m, sd, skew, kurt


def sharpe(x: list[float]) -> float:
    m, sd, *_ = moments(x)
    return m / sd


def psr(sr: float, n: int, skew: float, kurt: float, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio: P(SR vrai > benchmark)."""
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom <= 0:
        raise ValueError("denominateur PSR non positif (moments incoherents)")
    return _N.cdf((sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(denom))


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """E[max SR] sous H0 (edge nul) pour N essais independants."""
    if n_trials < 1:
        raise ValueError("n_trials >= 1")
    if n_trials == 1:
        return 0.0
    return math.sqrt(var_sr) * (
        (1 - EULER_GAMMA) * _N.inv_cdf(1 - 1.0 / n_trials)
        + EULER_GAMMA * _N.inv_cdf(1 - 1.0 / (n_trials * math.e))
    )


def dsr(returns: list[float], n_trials: int, var_sr_trials: float) -> float:
    """Deflated Sharpe Ratio. n_trials DOIT venir du registre (negatifs inclus)."""
    _, _, sk, ku = moments(returns)
    sr = sharpe(returns)
    sr0 = expected_max_sharpe(n_trials, var_sr_trials)
    return psr(sr, len(returns), sk, ku, sr0)


def min_track_record_length(sr: float, skew: float, kurt: float,
                            sr_benchmark: float = 0.0, confidence: float = 0.95) -> float:
    """Observations minimales pour que PSR >= confidence."""
    if sr <= sr_benchmark:
        return math.inf
    z = _N.inv_cdf(confidence)
    return 1 + (1 - skew * sr + (kurt - 1) / 4 * sr * sr) * (z / (sr - sr_benchmark)) ** 2


def required_sample_size(effect_sr: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """n pour detecter un Sharpe par periode `effect_sr` (test unilateral, iid).

    Optimiste: la dependance serielle et les queues epaisses augmentent n.
    """
    if effect_sr <= 0:
        raise ValueError("effect_sr > 0")
    z = _N.inv_cdf(1 - alpha) + _N.inv_cdf(power)
    return math.ceil((z / effect_sr) ** 2)


def purged_kfold(n: int, k: int, horizon: int, embargo: int):
    """Genere (train_idx, test_idx). Echantillon i a un label sur [i, i+horizon].

    Exclut du train: tout i dont le label chevauche le test, et les `embargo`
    observations suivant le test.
    """
    if not 2 <= k <= n:
        raise ValueError("2 <= k <= n")
    bounds = [round(j * n / k) for j in range(k + 1)]
    for j in range(k):
        ts, te = bounds[j], bounds[j + 1]
        test = list(range(ts, te))
        train = [i for i in range(n)
                 if not (i + horizon >= ts and i < te) and not (te <= i < te + embargo)]
        yield train, test


def stationary_bootstrap_ci(x: list[float], stat, mean_block: int = 10,
                            n_boot: int = 2000, alpha: float = 0.05, seed: int = 0):
    """IC percentile par bootstrap stationnaire (blocs geometriques)."""
    n = len(x)
    rng = random.Random(seed)
    p = 1.0 / mean_block
    out = []
    for _ in range(n_boot):
        s = []
        i = rng.randrange(n)
        while len(s) < n:
            s.append(x[i])
            i = rng.randrange(n) if rng.random() < p else (i + 1) % n
        out.append(stat(s))
    out.sort()
    return out[int(alpha / 2 * n_boot)], out[int((1 - alpha / 2) * n_boot) - 1]
