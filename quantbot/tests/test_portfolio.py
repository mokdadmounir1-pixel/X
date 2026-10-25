import numpy as np
import pandas as pd

from quantbot.portfolio.combine import combine, diagnostics, weights_at


def _R(n=600, k=5, seed=0, mu=0.0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.normal(mu, 1.0, (n, k)), index=pd.date_range("2024-01-01", periods=n), columns=list("abcde"))


def test_weights_causal_and_normalised():
    R = _R(); w = weights_at(R, 300, 120, "tilt"); assert abs(w.sum() - 1) < 1e-9 and (w >= 0).all()
    R2 = R.copy(); R2.iloc[300:] = 999.0                              # le futur ne change rien aux poids
    assert np.allclose(w, weights_at(R2, 300, 120, "tilt")) and np.allclose(weights_at(R, 10, 120, "invvol"), 0.2)


def test_combine_is_prefix_equal_and_diversifies_noise():
    R = _R(); full = combine(R, "tilt", target_vol=1.0); part = combine(R.iloc[:400], "tilt", target_vol=1.0)
    pd.testing.assert_series_equal(full.iloc[:400], part)
    d = diagnostics(R, combine(R, "invvol")); assert d["vol_r_day"] < 0.6 and d["diversification_ratio"] > 1.8 and abs(d["avg_pair_corr"]) < 0.15


def test_combining_zero_edge_streams_creates_no_mean():
    r = [combine(_R(seed=s), "invvol").mean() for s in range(40)]
    assert abs(np.mean(r)) < 0.03


def test_run_portfolio_script_from_cache(tmp_path):
    import importlib.util, json
    R = _R(n=700, k=4); R.index = pd.date_range("2022-01-03", periods=700)
    d = tmp_path / "reports" / "p"; d.mkdir(parents=True); R.to_csv(d / "daily_R.csv")
    spec = {"name": "p", "sources": [], "schemes": {"invvol": "x"}, "vol_target": {"target_r_day": 1.0, "window": 60, "max_scale": 3.0}, "gates": {"min_days": 250, "sign_flip_alpha": 0.025, "dsr_min": 0.95, "block": 5}}
    sp = tmp_path / "s.json"; sp.write_text(json.dumps(spec))
    m = importlib.util.spec_from_file_location("run_portfolio", "scripts/run_portfolio.py"); mod = importlib.util.module_from_spec(m); m.loader.exec_module(mod)
    assert mod.main([str(sp), "--root", str(tmp_path), "--cache"]) == 0
    assert json.loads((d / "result.json").read_text())["schemes"]["invvol"]["verdict"] in ("FAIL", "NON_CONCLUANT")
