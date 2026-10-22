import math, random
import pytest
from nexus import stats


def test_psr_half_at_benchmark():
    assert stats.psr(0.1, 100, 0.0, 3.0, sr_benchmark=0.1) == pytest.approx(0.5)


def test_psr_known_value():
    # SR=0.2/periode, n=100, normal: z = 0.2*sqrt(99)/sqrt(1+0.5*0.04)=1.9689 -> 0.9755
    assert stats.psr(0.2, 100, 0.0, 3.0) == pytest.approx(0.97553, abs=1e-4)


def test_expected_max_sharpe_increases_with_trials():
    a = stats.expected_max_sharpe(10, 0.01)
    b = stats.expected_max_sharpe(1000, 0.01)
    assert 0 < a < b and stats.expected_max_sharpe(1, 0.01) == 0.0


def test_dsr_rejects_best_of_noise():
    rng = random.Random(1)
    n_trials, n = 200, 750
    runs = [[rng.gauss(0, 0.01) for _ in range(n)] for _ in range(n_trials)]
    srs = [stats.sharpe(r) for r in runs]
    best = runs[srs.index(max(srs))]
    mean = sum(srs) / n_trials
    var = sum((s - mean) ** 2 for s in srs) / (n_trials - 1)
    naive = stats.psr(max(srs), n, *stats.moments(best)[2:])
    deflated = stats.dsr(best, n_trials, var)
    assert naive > deflated
    assert deflated < 0.95          # l'edge nul n'est pas "valide"


def test_mintrl_and_sample_size():
    assert math.isinf(stats.min_track_record_length(0.0, 0, 3))
    assert stats.required_sample_size(0.1) == 619   # (1.6449+0.8416)^2/0.01 -> 618.2 -> 619


def test_purged_kfold_no_leak():
    n, h, e = 100, 5, 3
    for train, test in stats.purged_kfold(n, 5, h, e):
        ts, te = test[0], test[-1] + 1
        assert not set(train) & set(test)
        for i in train:
            assert not (i + h >= ts and i < te)       # pas de chevauchement de label
            assert not (te <= i < te + e)             # embargo
        assert len(train) < n - len(test)             # purge effective


def test_bootstrap_ci_contains_mean_and_deterministic():
    rng = random.Random(3)
    x = [rng.gauss(0.5, 1) for _ in range(300)]
    lo, hi = stats.stationary_bootstrap_ci(x, lambda s: sum(s) / len(s), seed=7, n_boot=500)
    assert lo < sum(x) / 300 < hi
    assert (lo, hi) == stats.stationary_bootstrap_ci(x, lambda s: sum(s) / len(s), seed=7, n_boot=500)
