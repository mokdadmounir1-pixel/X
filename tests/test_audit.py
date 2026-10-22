import json
import numpy as np
import pandas as pd
import pytest
from helpers import *
from ftmo_algo.engine.sim import SimConfig, Sim
from ftmo_algo.registry import TrialRegistry, family_key
from ftmo_algo.research import stats as st
from ftmo_algo.research.gates import verdict, GateCfg
from ftmo_algo.research.wf import make_surrogate_stationary, shift_signals
from ftmo_algo.data.synth import make_universe
from ftmo_algo.evolve import insights as ins
from ftmo_algo.evolve.scenarios import make_trades, SCENARIOS

FLAT = [(100, 100.5, 99.5, 100)] * 6


def test_ambiguous_bar_policy_is_explicit_and_bounded():
    rows = FLAT + [(100, 100.2, 99.8, 100), (100, 106, 98, 105)]       # stop (99) ET cible (103) dans la barre
    mk = market(rows)
    sig = signal(mk, 5, 1, 99.0, 103.0)
    lo = run(mk, sig).trades.iloc[0]
    hi = Sim({"TEST": mk}, SimConfig(min_rr_net=0.0, use_guardian=False, ambiguity="target")).run([sig]).trades.iloc[0]
    assert lo.reason == "stop" and lo.amb and hi.reason == "cible" and hi.amb and hi.r > lo.r
    rnd = Sim({"TEST": mk}, SimConfig(min_rr_net=0.0, use_guardian=False, ambiguity="random")).run([sig]).trades.iloc[0]
    assert rnd.reason in ("stop", "cible")


def test_unambiguous_bar_not_flagged():
    rows = FLAT + [(100, 100.2, 99.8, 100), (100, 104, 99.9, 103)]
    mk = market(rows)
    assert not run(mk, signal(mk, 5, 1, 99.0, 103.0)).trades.iloc[0].amb


def test_vol_dependent_slippage_only_hurts_and_default_is_unchanged():
    rows = FLAT + [(100, 100.2, 99.8, 100), (100, 100.3, 96.0, 97)]      # barre large qui traverse le stop
    mk = market(rows, COSTLY)
    base = run(mk, signal(mk, 5, 1, 99.0, 103.0)).trades.iloc[0]
    same = Sim({"TEST": mk}, SimConfig(min_rr_net=0.0, use_guardian=False, vol_slip=0.0)).run([signal(mk, 5, 1, 99.0, 103.0)]).trades.iloc[0]
    wide = Sim({"TEST": mk}, SimConfig(min_rr_net=0.0, use_guardian=False, vol_slip=1.0)).run([signal(mk, 5, 1, 99.0, 103.0)]).trades.iloc[0]
    assert base.pnl == same.pnl and wide.pnl <= base.pnl


def test_registry_chain_tamper_detection_and_prior_trials(tmp_path):
    reg = TrialRegistry(tmp_path / "r.jsonl")
    fam = family_key(["US500", "EURUSD"], True)
    r1 = reg.log("research", fam, 100, "h1", ["a"], {"x": 1})
    reg.log("research", fam, 50, "h2", ["a"], {"x": 2})
    reg.log("research", family_key(["US500"], True), 999, "h3", ["a"], {})           # autre famille : ignorée
    reg.log("research", fam, 100, "h1", ["a"], {"x": 1})                              # ré-exécution identique : comptée une fois
    assert reg.verify()[0]
    assert reg.prior_trials(fam) == 150
    assert reg.prior_trials(fam, exclude_experiment=r1["experiment"]) == 50
    lines = (tmp_path / "r.jsonl").read_text().splitlines()
    rec = json.loads(lines[1]); rec["n_trials"] = 1
    lines[1] = json.dumps(rec); (tmp_path / "r.jsonl").write_text("\n".join(lines) + "\n")
    ok, msg = reg.verify()
    assert not ok and "rompue" in msg


def test_reality_check_rejects_noise_and_detects_real_mean():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 1, (400, 8))
    assert st.reality_check(noise, B=500, seed=1)["p"] > 0.10
    real = noise.copy(); real[:, 3] += 0.35
    assert st.reality_check(real, B=500, seed=1)["p"] < 0.05


def test_stationary_surrogate_is_valid_ohlc_and_destroys_order():
    dfs = make_universe(["EURUSD"], seed=3, years=1.0, persistence=0.5)
    d = dfs["EURUSD"]
    s = make_surrogate_stationary(d, 1)
    assert len(s) == len(d) and (s.high >= s[["open", "close"]].max(axis=1) - 1e-9).all() and (s.low <= s[["open", "close"]].min(axis=1) + 1e-9).all()
    day = lambda x: np.log(x.close).diff().fillna(0).groupby(x.index.normalize()).sum().to_numpy()
    ac = lambda x: np.corrcoef(x[:-1], x[1:])[0, 1]
    assert ac(day(d)) > 0.1 and abs(ac(day(s))) < 0.5 * ac(day(d))    # la persistance à l'échelle du jour (edge planté) est détruite


def test_shift_signals_keeps_relative_distances():
    from ftmo_algo.algos.base import Signals
    n = 50
    c = np.linspace(100, 150, n)
    s = Signals("t", "X", np.zeros(n, np.int8), np.full(n, np.nan), np.full(n, np.nan), np.zeros(n, np.int8))
    s.side[10] = 1; s.stop[10] = c[10] * 0.99; s.target[10] = c[10] * 1.03; s.grade[10] = 2
    t = shift_signals(s, c, 7)
    assert t.side[17] == 1 and abs(t.stop[17] / c[17] - 0.99) < 1e-12 and abs(t.target[17] / c[17] - 1.03) < 1e-12 and t.side[10] == 0


def test_exclusion_requires_stability_in_both_halves():
    tv = make_trades(SCENARIOS["nul"], seed=3, months=48, bad_session=(0, "london"))
    df = tv["scenario"]["v0@fixed3"].copy()
    assert "sess:london" in ins.analyze(ins.prep(df), B=499)["exclude"]
    d = ins.prep(df).sort_values("entry_t").reset_index(drop=True)
    first = d.index < len(d) // 2
    d.loc[first & (d.sess == "london"), "r"] = 3.0             # la zone n'est perdante que dans la 2e moitié
    assert "sess:london" not in ins.analyze(d, B=499)["exclude"]


def test_eliminatory_gate_failure_cannot_be_watch():
    cfg = GateCfg()
    g = {"g1_n_oos": (True, 100, 60), "g2_expectancy": (False, 0.2, 0.3), "g5_costs_x2": (False, -0.1, 0.0)}
    v, why = verdict(g, 0.9, 5.0, cfg, 0.2)
    assert v == "FAIL" and "ÉLIMINATOIRE" in why and "g5_costs_x2" in why
    g["g5_costs_x2"] = (True, 0.05, 0.0)
    assert verdict(g, 0.9, 5.0, cfg, 0.2)[0] == "WATCH"


def test_stress_table_worse_expectancy_never_safer():
    from ftmo_algo.target import stress_table
    from ftmo_algo.engine.guardian import PropProfile
    rng = np.random.default_rng(1)
    n = 400
    t0 = pd.Timestamp("2022-01-03", tz="UTC").value
    tr = pd.DataFrame({"r": np.where(rng.random(n) < 0.35, 3.0, -1.0),
                       "exit_t": np.sort(t0 + rng.integers(0, 700 * 86_400 * 10**9, n))})
    tab = stress_table(tr, PropProfile(), 1.0, shifts=(0.0, -0.3), paths=600)
    assert tab[1]["p_violation"] >= tab[0]["p_violation"] and tab[1]["median_month_pct"] <= tab[0]["median_month_pct"]


def test_research_reports_audit_fields(tmp_path):
    from ftmo_algo.research.pipeline import research
    dfs = make_universe(["EURUSD"], seed=5, years=3.0)
    rep = research(dfs, workers=1, null_B=9, do_locked=False, verbose=False, algos=["session_orb", "meanrev_z"], out_dir=str(tmp_path))
    assert "reality_check" in rep and rep["trials_registry"]["chaine"] == "chaîne intacte"
    a = rep["algos"]["session_orb"]
    assert "intrabar" in a and a["intrabar"]["ecart_E_R"] >= -1e-9          # cible-d'abord ≥ stop-d'abord
    assert all("classe" in v for v in a["gates"].values())
    rep2 = research(dfs, workers=1, null_B=9, do_locked=False, verbose=False, algos=["session_orb"], out_dir=str(tmp_path))
    assert rep2["trials_registry"]["essais_anterieurs_comptes_dans_le_DSR"] >= 0
    reg = TrialRegistry(tmp_path / "trials_registry.jsonl")
    assert len(reg.rows()) == 2 and reg.verify()[0]
