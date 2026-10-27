"""Exécute specs/alpha_miner_v1.json : rejoue les trades de l'or (recherche seulement), construit le jeu de données, juge hors-échantillon. Un essai compté.

    python scripts/run_alpha_miner.py specs/alpha_miner_v1.json
"""
import argparse, json, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.alpha_miner.dataset import FEATURES, build_dataset, feature_frame
from quantbot.alpha_miner.miner import auc_null_p, chrono_split, fit_predict, loser_clusters, permutation_importance, propose_rules
from quantbot.backtest.engine import Backtester
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.lab.locked import split_locked
from quantbot.lab.registry import TrialRegistry, canonical_hash
from quantbot.lab.specs import build_settings
from quantbot.strategies.build import events_for
from quantbot.strategies.events import EventSignalEngine


def gather(root: Path, spec: dict) -> pd.DataFrame:
    parts, feats, research = [], None, None
    for src in spec["sources"]:
        s = json.loads((root / src).read_text(encoding="utf-8")); inst = spec["instrument"]; df = load_mt5_csv(root / "data" / "real" / s["instruments"][inst])
        research, _ = split_locked(df, s["lock_months"], s["lock_min_frac"]); measured = costs_from_frame(df)
        feats = feats if feats is not None else feature_frame(research)               # une seule fois : les barres de recherche sont les mêmes pour toutes les specs
        for name, scfg in s["strategies"].items():
            if inst not in scfg["instruments"]:
                continue
            st = build_settings(s, inst, measured, research).with_overrides({"backtest.max_hold_bars": scfg["max_hold_bars"]})
            bt = Backtester(st, signal_engine=EventSignalEngine(st, events_for(name, scfg, research))).run(research)
            d = build_dataset(research, bt.trades, name, feats); parts.append(d); print(f"  {name}: {len(d)} trades", flush=True)
    return pd.concat(parts, ignore_index=True)


def main(argv=None) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("spec"); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--dataset", help="CSV déjà construit (saute le rejeu)")
    a = ap.parse_args(argv); root = Path(a.root); spec = json.loads(Path(a.spec).read_text(encoding="utf-8")); out_dir = root / "reports" / spec["name"]; out_dir.mkdir(parents=True, exist_ok=True)
    ds = pd.read_csv(a.dataset, parse_dates=["entry_time", "exit_time"]) if a.dataset else gather(root, spec)
    ds.to_csv(out_dir / "dataset.csv", index=False); g = spec["gates"]; res = {"spec": spec["name"], "n_trades": int(len(ds)), "features": FEATURES}
    ok = ds.dropna(subset=FEATURES).copy(); train, test = chrono_split(ok, spec["split"]["train_frac"], gap_days=spec["split"]["gap_days"]); res.update(n_usable=int(len(ok)), n_train=int(len(train)), n_test=int(len(test)))
    if len(ds) < g["min_trades"] or len(test) < 100:
        res["verdict"] = "NON_CONCLUANT"
    else:
        m, p = fit_predict(train, test, FEATURES, spec["model"]["rounds"]); nul = auc_null_p(test["win"].to_numpy(), p); imp = permutation_importance(m, test, FEATURES)
        res.update(holdout=nul, permutation_importance=dict(sorted(imp.items(), key=lambda kv: -kv[1])), base_win_rate_test=float(test["win"].mean()), base_mean_r_test=float(test["r"].mean()),
                   loser_clusters=loser_clusters(ok, FEATURES), rules=propose_rules(train, test, FEATURES, tuple(spec["rules"]["quantiles"]), spec["rules"]["min_keep_frac"], spec["rules"]["alpha"]))
        res["verdict"] = "SIGNAL" if (nul["p_value"] <= g["auc_null_alpha"] and nul["auc"] >= g["min_auc"]) else "RIEN"
    reg = TrialRegistry(root / "reports" / "registry.jsonl"); kept = [r for r in res.get("rules", {}).get("rules", []) if r["retained"]]
    reg.record_trial(canonical_hash({"spec": spec["name"], "split": spec["split"], "model": spec["model"], "rules": spec["rules"]}), canonical_hash({"n": int(len(ds)), "last": str(ds["exit_time"].max())}), float(res.get("holdout", {}).get("auc", 0.5) - 0.5), int(len(ds)), strategy="alpha_miner")
    (out_dir / "result.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"Trades {res['n_trades']} (apprentissage {res.get('n_train')}, test {res.get('n_test')}) -> {res['verdict']}")
    if "holdout" in res:
        h = res["holdout"]; print(f"AUC hors-échantillon {h['auc']:.3f} (nulle {h['null_mean']:.3f}, p = {h['p_value']:.3f})"); print("Variables (baisse d'AUC si mélangée) :", {k: round(v, 4) for k, v in list(res["permutation_importance"].items())[:5]})
        print(f"Règles essayées {res['rules']['rules_tried']}, testées hors-échantillon {res['rules']['rules_tested_on_holdout']}, retenues {len(kept)}")
    print(f"Essais comptés : {reg.n_trials()}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
