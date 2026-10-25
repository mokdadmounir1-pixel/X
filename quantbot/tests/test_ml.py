import numpy as np
import pandas as pd

from quantbot.ml.cv import PurgedKFold
from quantbot.ml.features import build_features, ffd_weights, frac_diff_ffd
from quantbot.ml.model import MLParams, auc, make_labels, simulate, walk_forward_proba


def _bars(n=4000, seed=0, drift=0.0):
    rng = np.random.default_rng(seed); c = 100 * np.exp(np.cumsum(rng.normal(drift, 0.002, n))); o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + abs(rng.normal(0, 0.0005, n))); l = np.minimum(o, c) * (1 - abs(rng.normal(0, 0.0005, n)))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.integers(50, 500, n).astype(float), "spread": 0.0},
                        index=pd.date_range("2024-01-01", periods=n, freq="15min"))


def test_fracdiff_d1_is_first_difference_and_weights():
    x = np.cumsum(np.random.default_rng(0).normal(size=300))
    assert np.allclose(frac_diff_ffd(x, 1.0)[1:], np.diff(x)) and len(ffd_weights(0.4)) > 10


def test_features_are_causal():
    df = _bars(1500); f_full = build_features(df)
    cut = 1000; f_cut = build_features(df.iloc[:cut])
    pd.testing.assert_frame_equal(f_full.iloc[:cut], f_cut, check_exact=False, rtol=1e-9, atol=1e-12)


def test_purged_kfold_no_overlap_and_embargo():
    n, h = 1000, 10; le = np.minimum(np.arange(n) + h, n - 1)
    for tr, te in PurgedKFold(5, 0.02).split(le):
        assert len(np.intersect1d(tr, te)) == 0
        assert not np.any((tr <= le[te].max()) & (le[tr] >= te[0]))          # aucun chevauchement d'étiquette
        after = tr[tr > te[-1]]
        assert len(after) == 0 or after.min() >= te[-1] + 1 + int(np.ceil(n * 0.02))


def test_auc_basic():
    assert auc(np.array([0, 0, 1, 1]), np.array([.1, .2, .8, .9])) == 1.0 and auc(np.array([0, 1]), np.array([.9, .1])) == 0.0


def test_walk_forward_on_pure_noise_finds_no_edge_and_labels_end_unlabeled():
    df = _bars(); y, le = make_labels(df.close.to_numpy(), 8)
    assert (y[-8:] == -1).all()
    p = MLParams(min_train=1500, refit_every=800); proba, log = walk_forward_proba(build_features(df), y, le, p)
    assert np.isnan(proba[:1500]).all() and log
    ok = ~np.isnan(proba) & (y >= 0)
    assert 0.45 < auc(y[ok], proba[ok]) < 0.56                         # bruit pur : pas d'avantage
    tr = simulate(df, proba, MLParams(threshold=0.55))
    assert all(t["entry_i"] >= 1500 for t in tr)


def test_walk_forward_finds_real_structure_when_present():
    df = _bars(5000); e = np.random.default_rng(1).normal(0, 0.002, len(df)); r = np.zeros(len(df))
    for t in range(1, len(r)):
        r[t] = 0.5 * r[t - 1] + e[t]                                     # momentum AR(1) injecté (test uniquement)
    c = 100 * np.exp(np.cumsum(r))
    df["close"] = c; df["open"] = np.r_[c[0], c[:-1]]; df["high"] = np.maximum(df.open, df.close) * 1.0003; df["low"] = np.minimum(df.open, df.close) * 0.9997
    y, le = make_labels(c, 1); p = MLParams(horizon=1, min_train=2000, refit_every=1000)
    proba, _ = walk_forward_proba(build_features(df), y, le, p, cv_diag=False)
    ok = ~np.isnan(proba) & (y >= 0); assert auc(y[ok], proba[ok]) > 0.58
