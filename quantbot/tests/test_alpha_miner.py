import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

from quantbot.alpha_miner import dataset as dsm, miner as mn
from tests.test_apex import _trending


def _ds(n=3000, planted=False, seed=0):
    rng = np.random.default_rng(seed); t0 = pd.Timestamp("2022-01-03"); X = {f: rng.normal(size=n) for f in dsm.FEATURES}
    entry = t0 + pd.to_timedelta(np.arange(n) * 6, unit="h"); lat = X["atr_ratio"]
    p = 0.5 + (0.12 * np.tanh(lat) if planted else 0.0); win = (rng.uniform(size=n) < p).astype(int)
    r = np.where(win == 1, 1.0, -1.0) + rng.normal(0, 0.1, n)
    return pd.DataFrame({**X, "strategy": "s", "entry_time": entry, "exit_time": entry + pd.Timedelta(hours=3), "r": r, "win": win, "mfe_r": 1.0, "mae_r": 1.0, "bars_held": 4})


def test_noise_dataset_yields_no_significant_auc_and_no_retained_rule():
    ds = _ds(); tr, te = mn.chrono_split(ds); assert tr["exit_time"].max() < te["entry_time"].min()          # aucune fuite chronologique
    m, p = mn.fit_predict(tr, te, dsm.FEATURES, 80); h = mn.auc_null_p(te["win"].to_numpy(), p, n=200)
    assert h["p_value"] > 0.01 and abs(h["auc"] - 0.5) < 0.06
    assert mn.propose_rules(tr, te, dsm.FEATURES)["rules_tried"] > 20
    fp = 0
    for sd in range(100, 130):                                                                                              # taux de fausses règles sur 30 jeux de BRUIT : doit rester proche de alpha = 5 %
        a, b = mn.chrono_split(_ds(3000, seed=sd)); fp += any(r["retained"] for r in mn.propose_rules(a, b, dsm.FEATURES)["rules"])
    assert fp <= 4


def test_planted_effect_is_found_out_of_sample_with_correct_feature():
    ds = _ds(6000, planted=True); tr, te = mn.chrono_split(ds); m, p = mn.fit_predict(tr, te, dsm.FEATURES, 150)
    h = mn.auc_null_p(te["win"].to_numpy(), p, n=200); imp = mn.permutation_importance(m, te, dsm.FEATURES, repeats=5)
    assert h["auc"] > 0.55 and h["p_value"] < 0.05 and max(imp, key=imp.get) == "atr_ratio"


def test_dataset_features_are_causal_and_excursions_are_computed_in_r():
    df = _trending(3000); f = dsm.feature_frame(df); i = 2500; d2 = df.copy(); d2.iloc[i + 1:, d2.columns.get_loc("close")] *= 1.1      # on altère le futur
    f2 = dsm.feature_frame(d2); cols = [c for c in dsm.FEATURES if c != "side"]
    assert np.allclose(f.loc[df.index[i], cols].to_numpy(float), f2.loc[df.index[i], cols].to_numpy(float), equal_nan=True)
    from quantbot.execution.broker import Trade
    t = Trade("long", df.index[2000], df.index[2005], float(df.close.iloc[2000]), float(df.close.iloc[2005]), 1.0, 10.0, "x", stop=float(df.close.iloc[2000]) - 5.0, nominal_risk=10.0)
    row = dsm.build_dataset(df, [t], "s", f).iloc[0]; assert row["mfe_r"] >= 0 and row["mae_r"] >= 0 and row["r"] == 1.0


def test_kmeans_and_clusters_report_z_scores():
    ds = _ds(2000); cl = mn.loser_clusters(ds, dsm.FEATURES, 3); assert sum(c["n"] for c in cl) == len(ds) and all("z_vs_global" in c for c in cl)


def test_script_runs_on_a_prebuilt_dataset_and_never_applies_rules(tmp_path):
    ds = _ds(2500); p = tmp_path / "d.csv"; ds.to_csv(p, index=False)
    spec = {"name": "am", "sources": [], "instrument": "XAUUSD", "split": {"train_frac": 0.6, "gap_days": 3.0}, "model": {"rounds": 60}, "rules": {"quantiles": [0.2, 0.8], "min_keep_frac": 0.3, "alpha": 0.05}, "gates": {"min_trades": 1000, "auc_null_alpha": 0.05, "min_auc": 0.53}}
    import json; sp = tmp_path / "s.json"; sp.write_text(json.dumps(spec))
    s = importlib.util.spec_from_file_location("run_alpha_miner", Path(__file__).resolve().parents[1] / "scripts" / "run_alpha_miner.py"); mod = importlib.util.module_from_spec(s); s.loader.exec_module(mod)
    assert mod.main([str(sp), "--root", str(tmp_path), "--dataset", str(p)]) == 0
    res = json.loads((tmp_path / "reports" / "am" / "result.json").read_text()); assert res["verdict"] in ("RIEN", "SIGNAL", "NON_CONCLUANT") and "holdout" in res


def test_rule_report_keeps_train_and_test_gains_distinct():
    ds = _ds(6000, planted=True); tr, te = mn.chrono_split(ds); rules = mn.propose_rules(tr, te, dsm.FEATURES)["rules"]
    assert rules and any(abs(r["train_gain_r"] - r["test_gain_r"]) > 1e-9 for r in rules)
