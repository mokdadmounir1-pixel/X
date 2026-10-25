import numpy as np
import pandas as pd
import pytest

from quantbot.config import Settings
from quantbot.core.calibration import Curve, StratifiedModel, fit_stratified
from tests.synthetic import generate_synthetic
from quantbot.data.mtf import bias, group_keys, htf_state, resample_base
from quantbot.signals.mtf_calibrated import MTFCalibratedSignalEngine


def _m15(days=120, seed=3):
    df = generate_synthetic(days * 96, seed=seed, freq="15min", start="2024-01-02")
    return df[df.index.dayofweek < 5]  # pas de week-end


def test_group_keys_roll_at_ny_5pm_and_h4_has_six_blocks_per_day():
    idx = pd.date_range("2024-07-02 20:00", periods=40, freq="15min")  # été : 17:00 NY = 21:00 UTC
    d1, h4 = group_keys(idx, "1D"), group_keys(idx, "4h")
    assert d1[idx.get_loc(pd.Timestamp("2024-07-02 20:45"))] != d1[idx.get_loc(pd.Timestamp("2024-07-02 21:00"))]
    assert d1[idx.get_loc(pd.Timestamp("2024-07-02 21:00"))] == d1[idx.get_loc(pd.Timestamp("2024-07-02 23:45"))]
    full = pd.date_range("2024-07-02 21:00", periods=96, freq="15min")
    assert len(set(group_keys(full, "4h"))) == 6 and len(set(group_keys(full, "1D"))) == 1
    with pytest.raises(ValueError):
        group_keys(idx, "3h")


def test_resample_base_ohlc_integrity():
    df = _m15(30)
    h1 = resample_base(df, "1h")
    first_hour = h1.index[3]
    members = df[(df.index >= first_hour) & (df.index < first_hour + pd.Timedelta(hours=1))]
    assert h1["high"].iloc[3] == members["high"].max() and h1["low"].iloc[3] == members["low"].min()
    assert h1["open"].iloc[3] == members["open"].iloc[0] and h1["close"].iloc[3] == members["close"].iloc[-1]
    assert h1["volume"].iloc[3] == members["volume"].sum() and (h1["high"] >= h1["low"]).all()


def test_bias_is_causal_future_changes_never_alter_the_past():
    df = _m15(150)
    k = 9000
    full = bias(df)
    trunc = bias(df.iloc[:k])
    assert (full.iloc[:k].to_numpy() == trunc.to_numpy()).all()  # tronquer le futur ne change rien
    altered = df.copy()
    altered.iloc[k:, :4] = altered.iloc[k:, :4].to_numpy() * 3.0
    assert (bias(altered).iloc[:k].to_numpy() == full.iloc[:k].to_numpy()).all()  # le saboter non plus


def test_bias_only_sees_completed_htf_bars():
    df = _m15(150)
    gid = group_keys(df.index, "1D")
    st = htf_state(df, "1D")
    # à l'intérieur d'un même jour de marché, l'état ne change JAMAIS (il vient du jour précédent, terminé)
    for g in np.unique(gid)[60:80]:
        assert st[gid == g].nunique() == 1


def test_bias_detects_a_trending_market_and_is_mixed_in_noise():
    n = 150 * 96
    idx = pd.date_range("2024-01-01", periods=n, freq="15min")
    up = pd.DataFrame({"open": 100 + np.arange(n) * 0.01, "high": 100.05 + np.arange(n) * 0.01, "low": 99.95 + np.arange(n) * 0.01,
                       "close": 100.01 + np.arange(n) * 0.01, "volume": 1.0}, index=idx)
    b = bias(up)
    assert (b.iloc[-2000:] == 1).mean() > 0.95 and (b.iloc[:50] == 0).all()  # échauffement neutre
    down = up.copy(); down[["open", "high", "low", "close"]] = 300 - up[["open", "high", "low", "close"]].to_numpy()
    assert (bias(down).iloc[-2000:] == -1).mean() > 0.95


def test_stratified_model_decision_roundtrip_and_hash(tmp_path):
    hi = Curve([0.4, 1.0], [0.5, 0.5], 500, 0.4)
    lo = Curve([0.4, 1.0], [-0.3, -0.3], 500, 0.4)
    m = StratifiedModel({"long|1": hi, "long|0": lo, "long|-1": lo, "short|1": lo, "short|0": lo, "short|-1": hi}, 0.1)
    assert m.decide(0.9, 0.9, 1)[0] == "bullish"      # achat accepté seulement en tendance haussière
    assert m.decide(0.9, 0.9, -1)[0] == "bearish"     # vente acceptée seulement en tendance baissière
    assert m.decide(0.9, 0.9, 0) is None              # contexte mixte : abstention
    p = tmp_path / "m.json"; m.save(p)
    assert StratifiedModel.load(p).hash() == m.hash()
    assert StratifiedModel({**m.curves}, 0.2).hash() != m.hash()


def test_fit_stratified_learns_state_dependent_expectancy_without_inventing_any():
    rng = np.random.default_rng(0)
    n = 6000
    bull = rng.uniform(0.35, 1.0, n); bear = rng.uniform(0.35, 1.0, n)
    state = rng.choice([-1, 0, 1], n)
    long_r = rng.normal(-0.05, 1.0, n) + 0.8 * (state == 1) * (bull > 0.7)   # edge planté : achats forts EN tendance haussière
    short_r = rng.normal(-0.05, 1.0, n)
    m = fit_stratified(bull, bear, long_r, short_r, state, np.ones(n, bool), 0.35, 300, 0.1)
    assert m.curves["long|1"].predict(0.95) > 0.4                      # retrouvé
    assert m.curves["long|-1"].predict(0.95) < 0.2                     # non contaminé
    assert max(m.curves["short|1"].predict(0.95), m.curves["short|0"].predict(0.95), m.curves["short|-1"].predict(0.95)) < 0.25


def test_mtf_engine_uses_the_precomputed_state_and_abstains_when_unlisted():
    s = Settings.from_dict({"tolerance": {"min_score": 0.3}, "signals": {"atr_floor_frac": 0.5}})
    df = generate_synthetic(900, seed=2, freq="1h")
    always = Curve([0.3, 1.0], [0.9, 0.9], 999, 0.3); never = Curve([0.3, 1.0], [-0.9, -0.9], 999, 0.3)
    model = StratifiedModel({f"{side}|{st}": (always if st == 1 else never) for side in ("long", "short") for st in (-1, 0, 1)}, 0.1)
    up = MTFCalibratedSignalEngine(s, model, pd.Series(1, index=df.index))
    flat = MTFCalibratedSignalEngine(s, model, pd.Series(0, index=df.index))
    sigs = [up.evaluate(df.iloc[: t + 1].tail(300)) for t in range(300, 900, 9)]
    assert any(x is not None for x in sigs)
    assert all(flat.evaluate(df.iloc[: t + 1].tail(300)) is None for t in range(300, 900, 9))
