import numpy as np

from quantbot.risk.var import fractional_kelly, historical_var_es, parametric_var_es
from quantbot.stat.pairs import PairParams, adf_stat, engle_granger, simulate_pair


def _pair(n=6000, seed=0, coint=True):
    rng = np.random.default_rng(seed)
    b = np.cumsum(rng.normal(0, 0.002, n)) + 4.0
    if coint:
        s = np.zeros(n)
        for t in range(1, n):
            s[t] = 0.97 * s[t - 1] + rng.normal(0, 0.003)
    else:
        s = np.cumsum(rng.normal(0, 0.003, n))
    return np.exp(0.5 + 1.2 * b + s), np.exp(b)


def test_adf_separates_stationary_from_random_walk():
    rng = np.random.default_rng(1)
    rw = np.cumsum(rng.normal(size=3000)); st = np.zeros(3000)
    for t in range(1, 3000):
        st[t] = 0.9 * st[t - 1] + rng.normal()
    assert adf_stat(st) < -3.5 and adf_stat(rw) > -3.0


def test_engle_granger_detects_cointegration_and_rejects_independent_walks():
    a, b = _pair(coint=True); r = engle_granger(np.log(a), np.log(b))
    assert r["cointegrated"] and abs(r["beta"] - 1.2) < 0.1
    a, b = _pair(coint=False, seed=3)
    assert not engle_granger(np.log(a), np.log(b))["cointegrated"]


def test_simulation_is_causal_prefix_equal():
    a, b = _pair(); p = PairParams(warmup=300, coint_window=800)
    full = simulate_pair(a, a, b, b, p)
    cut = 4000
    part = simulate_pair(a[:cut], a[:cut], b[:cut], b[:cut], p)
    closed_before = [t for t in full if t["exit_i"] < cut - 2]
    assert [(t["entry_i"], t["exit_i"], t["side"]) for t in closed_before] == [(t["entry_i"], t["exit_i"], t["side"]) for t in part if t["exit_i"] < cut - 2]
    assert len(full) > 5


def test_costs_reduce_r_and_no_trade_without_cointegration_gate_open():
    a, b = _pair(); free = simulate_pair(a, a, b, b, PairParams(warmup=300, coint_window=800))
    costly = simulate_pair(a, a, b, b, PairParams(warmup=300, coint_window=800, cost_per_leg=0.001))
    assert sum(t["r"] for t in costly) < sum(t["r"] for t in free)
    a2, b2 = _pair(coint=False, seed=5)
    assert len(simulate_pair(a2, a2, b2, b2, PairParams(warmup=300, coint_window=800))) <= len(free)


def test_var_es_and_kelly():
    r = np.random.default_rng(2).normal(0, 0.01, 5000)
    p, h = parametric_var_es(r), historical_var_es(r)
    assert 0.015 < p["var"] < 0.018 and p["es"] > p["var"] and abs(h["var"] - p["var"]) < 0.002
    assert fractional_kelly(0.5, 1.0) == 0.0 and 0 < fractional_kelly(0.6, 2.0) <= 0.3


def test_run_pairs_script_end_to_end_on_synthetic_csv(tmp_path):
    import importlib.util, json, pandas as pd
    a, b = _pair(n=9000, seed=7)
    idx = pd.date_range("2024-01-01", periods=len(a), freq="15min")
    d = tmp_path / "data" / "crypto"; d.mkdir(parents=True)
    for nm, x in (("AAA-USD", a), ("BBB-USD", b)):
        pd.DataFrame({"time": idx.strftime("%Y-%m-%d %H:%M:%S+00:00"), "open": x, "high": x * 1.0001, "low": x * 0.9999, "close": x}).to_csv(d / f"{nm}_M15.csv", index=False)
    spec = {"name": "t", "legs": ["AAA-USD", "BBB-USD"], "timeframe": "M15", "data_dir": "data/crypto", "lock_months": 1,
            "params": {"warmup": 300, "coint_window": 800}, "variants": {"v": {"cost_per_leg": 0.0}}, "null": {"n_shifts": 5, "min_shift_bars": 500}}
    sp = tmp_path / "s.json"; sp.write_text(json.dumps(spec))
    m = importlib.util.spec_from_file_location("run_pairs", "scripts/run_pairs.py"); mod = importlib.util.module_from_spec(m); m.loader.exec_module(mod)
    assert mod.main([str(sp), "--root", str(tmp_path)]) == 0
    res = json.loads((tmp_path / "reports" / "t" / "result.json").read_text())
    assert res["variants"]["v"]["n_trades"] > 0 and idx[-1] - pd.Timestamp(res["end"]) >= pd.Timedelta(days=28)
