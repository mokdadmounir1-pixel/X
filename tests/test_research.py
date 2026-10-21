import numpy as np
import pandas as pd
import pytest
from ftmo_algo.data.synth import make_universe
from ftmo_algo.research import split, wf
from ftmo_algo.research.pipeline import research
from ftmo_algo.research import stats as st
from ftmo_algo.research.gates import GateCfg, null_gate


def test_locked_period_never_read_during_research(tmp_path):
    dfs = make_universe(["EURUSD"], seed=5, years=3.0)
    rdata, locked = split.split_locked(dfs)
    assert all(d.index[-1] < rdata.lock_start for d in rdata.dfs.values())
    with pytest.raises(PermissionError):
        locked._data()
    # poison : tout ce qui est après le verrou devient absurde -> la recherche doit donner EXACTEMENT le même rapport
    poisoned = {k: d.copy() for k, d in dfs.items()}
    for k, d in poisoned.items():
        m = d.index >= rdata.lock_start
        d.loc[m, ["open", "high", "low", "close"]] = d.loc[m, ["open", "high", "low", "close"]].to_numpy() * 7.0
    kw = dict(workers=1, null_B=9, do_locked=False, verbose=False, algos=["session_orb"], out_dir=str(tmp_path))
    a = research(dfs, **kw); b = research(poisoned, **kw)
    assert a["algos"]["session_orb"]["oos"] == b["algos"]["session_orb"]["oos"]
    assert a["algos"]["session_orb"]["modal_variant"] == b["algos"]["session_orb"]["modal_variant"]


def test_locked_evaluated_only_once(tmp_path):
    dfs = make_universe(["EURUSD"], seed=5, years=3.0)
    _, locked = split.split_locked(dfs)
    out = split.final_evaluation(locked, lambda full, ls: {"ok": 1}, str(tmp_path), "t")
    assert out == {"ok": 1}
    with pytest.raises(RuntimeError):
        split.final_evaluation(locked, lambda full, ls: {"ok": 2}, str(tmp_path), "t")


def test_null_test_runs_and_surrogate_kills_edge():
    dfs = make_universe(["EURUSD"], seed=9, years=2.0, persistence=0.5)
    sur = wf.make_surrogate(dfs["EURUSD"], 1)
    assert len(sur) == len(dfs["EURUSD"]) and (sur.high >= sur[["open", "close"]].max(axis=1) - 1e-9).all()
    p = null_gate(0.5, np.array([0.0, 0.1, -0.1, 0.05] * 10), 5, GateCfg())
    assert p[1] > 0 and p[2] < 0.1


def test_false_pass_rate_computed_on_random_walks():
    from ftmo_algo.research.calibrate import calibrate
    r = calibrate(("EURUSD",), n_series=2, years=3.0, null_B=9, workers=2, out="/tmp/calib_test.json")
    assert 0.0 <= r["false_pass_rate_per_series"] <= 1.0 and r["n_series"] == 2
    assert r["false_pass_rate_per_series"] == 0.0           # aucun faux PASS sur marche aléatoire


def test_target_module_never_uses_target_as_optimisation_objective():
    import inspect, ftmo_algo.research.pipeline as P, ftmo_algo.research.wf as W, ftmo_algo.research.gates as G
    for mod in (P, W, G):
        src = inspect.getsource(mod)
        assert "ftmo_algo.target" not in src and "from ..target" not in src and "import target" not in src
    assert "target" not in inspect.signature(P.research).parameters
    from ftmo_algo.target import monthly_mc
    from ftmo_algo.engine.guardian import PropProfile
    rng = np.random.default_rng(0)
    t = pd.DataFrame({"r": rng.normal(0.1, 1.5, 200), "exit_t": pd.date_range("2024-01-01", periods=200, freq="1D", tz="UTC").asi8})
    a = monthly_mc(t, 0.5, PropProfile(), paths=300, target_pct=5.0)
    b = monthly_mc(t, 0.5, PropProfile(), paths=300, target_pct=1.0)
    assert a["median_month_pct"] == b["median_month_pct"] and a["p_violation"] == b["p_violation"]   # la cible ne change que la mesure


def test_dsr_penalises_many_trials():
    rng = np.random.default_rng(1)
    r = rng.normal(0.05, 1, 300)
    few = st.deflated_sharpe(r, [0.0, 0.05], 2)
    many = st.deflated_sharpe(r, list(rng.normal(0, 0.1, 400)), 400)
    assert many < few
