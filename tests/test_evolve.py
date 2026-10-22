import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from ftmo_algo.evolve import insights as ins
from ftmo_algo.evolve.health import assess
from ftmo_algo.evolve.engine import EvolveCfg, evolve_all, summarize
from ftmo_algo.evolve.journal import EvoJournal
from ftmo_algo.evolve.scenarios import make_trades, SCENARIOS, run_scenario, calibrate_evolve


def test_health_detects_degradation_not_noise():
    rng = np.random.default_rng(0)
    good = np.where(rng.random(60) < 0.34, 3.0, -1.0)           # même loi que la référence
    bad = np.where(rng.random(60) < 0.15, 3.0, -1.0)
    assert assess(good, 0.15, 1.7)["state"] == "SAIN"
    assert assess(bad, 0.15, 1.7)["state"] in ("DEGRADE", "PAUSE")
    assert assess(good[:5], 0.15, 1.7)["state"] == "INSUFFISANT"


def test_insights_find_planted_bad_session_and_nothing_in_noise():
    tv = make_trades(SCENARIOS["nul"], seed=3, months=48, bad_session=(0, "london"))
    df = ins.prep(tv["scenario"]["v0@fixed3"])
    a = ins.analyze(df, B=499)
    assert "sess:london" in a["exclude"]
    clean = ins.prep(make_trades(SCENARIOS["nul"], seed=4)["scenario"]["v1@fixed3"])
    fp = sum(len(ins.analyze(ins.prep(make_trades(SCENARIOS["nul"], seed=s)["scenario"]["v1@fixed3"]), B=199)["exclude"]) > 0
             for s in range(10, 30))
    assert fp <= 4         # faux positifs bornés par le Šidák (alpha 10 % par série)


def test_causality_future_does_not_change_past_decisions():
    tv = make_trades(SCENARIOS["decay"], seed=1)["scenario"]
    cfg = EvolveCfg(seed=1)
    full = evolve_all({"a": tv}, cfg, EvoJournal(None))
    cut = pd.Timestamp("2024-06-01", tz="UTC")
    part = {k: d[d.entry_t < cut.value] for k, d in tv.items()}
    short = evolve_all({"a": part}, cfg, EvoJournal(None), t0=pd.Timestamp("2021-01-01", tz="UTC"), t1=cut)
    ev_s = [(e["event"], e["asof"]) for e in short["journal"].events if pd.Timestamp(e["asof"]) < cut - pd.DateOffset(months=3)]
    ev_f = [(e["event"], e["asof"]) for e in full["journal"].events if pd.Timestamp(e["asof"]) < cut - pd.DateOffset(months=3)]
    assert ev_s == ev_f


def test_null_scenario_does_not_manufacture_edge():
    gains = [run_scenario("nul", s)[1]["_portefeuille"]["gain_R_par_mois"] for s in range(12)]
    assert abs(np.mean(gains)) < 0.6          # ~0 en moyenne, sans biais systématique
    assert sum(run_scenario("nul", s)[1]["_portefeuille"]["verdict_evolution"].startswith("UTILE") for s in range(12)) <= 2


def test_decay_scenario_evolution_helps():
    gains = [run_scenario("decay", s)[1]["_portefeuille"]["gain_R_par_mois"] for s in range(12)]
    assert np.mean(gains) > 1.0


def test_state_resume_gives_same_decisions():
    tv = make_trades(SCENARIOS["decay"], seed=2)["scenario"]
    cfg = EvolveCfg(seed=2)
    whole = evolve_all({"a": tv}, cfg, EvoJournal(None))
    from ftmo_algo.evolve.engine import month_grid
    ep = month_grid(pd.Timestamp(min(d.entry_t.min() for d in tv.values()), tz="UTC"), pd.Timestamp(max(d.exit_t.max() for d in tv.values()), tz="UTC"), cfg)
    half = evolve_all({"a": tv}, cfg, EvoJournal(None), epochs=ep[:20])
    from ftmo_algo.evolve.engine import state_to_json
    import json
    st = json.loads(json.dumps(state_to_json(half), default=str))
    rest = evolve_all({"a": tv}, cfg, EvoJournal(None), state=st, epochs=ep)
    assert half["algos"]["a"]["variant"] != "" and rest["algos"]["a"]["variant"] == whole["algos"]["a"]["variant"]
    assert [e["event"] for e in half["journal"].events] + [e["event"] for e in rest["journal"].events] == [e["event"] for e in whole["journal"].events]
