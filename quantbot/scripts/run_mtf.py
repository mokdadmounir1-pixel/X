"""v3 : scores flous x contexte multi-timeframe (H4+D1, causal) -> calibration par (côté, état) -> évaluation hors échantillon.

Usage : python scripts/run_mtf.py specs/mtf_v3.json [--only EURUSD] [--tf H1]
Période verrouillée jamais lue. Un essai par (instrument, timeframe).
"""
import argparse, hashlib, json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quantbot.core.calibration import fit_stratified
from quantbot.core.labels import compute_labels
from quantbot.core.scores import compute_scores
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.data.mtf import bias as mtf_bias, resample_base
from quantbot.lab.gates import GateCfg
from quantbot.lab.locked import split_locked
from quantbot.lab.pipeline import data_hash, evaluate_research
from quantbot.lab.registry import TrialRegistry
from quantbot.lab.specs import build_settings
from quantbot.signals.mtf_calibrated import MTFCalibratedSignalEngine

EDGES = [0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 1.0001]


def cached_scores(base, settings, cache_dir):
    key = hashlib.sha256((data_hash(base) + json.dumps({k: v for k, v in settings.to_dict().items()
                          if k in ("tolerance", "detection", "signals")}, sort_keys=True)).encode()).hexdigest()[:20]
    f = cache_dir / f"scores_{key}.npz"
    if f.exists():
        z = np.load(f); return z["bull"], z["bear"]
    bull, bear = compute_scores(base, settings)
    np.savez(f, bull=bull, bear=bear)
    return bull, bear


def cell_table(score, y, state, tr, va, side):
    rows = {}
    for st in (-1, 0, 1):
        for name, lo in (("score>=0.65", 0.65), ("score 0.35-0.65", 0.35)):
            hi = 1.0001 if lo == 0.65 else 0.65
            mt = tr & (state == st) & (score >= lo) & (score < hi) & np.isfinite(y)
            mv = va & (state == st) & (score >= lo) & (score < hi) & np.isfinite(y)
            rows[f"{side}|état{st:+d}|{name}"] = {"n_train": int(mt.sum()), "E_train": round(float(y[mt].mean()), 4) if mt.any() else None,
                                                  "n_valid": int(mv.sum()), "E_valid": round(float(y[mv].mean()), 4) if mv.any() else None}
    return rows


def main():
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--only"); ap.add_argument("--tf")
    ap.add_argument("--registry", default=str(ROOT / "reports" / "registry.jsonl"))
    args = ap.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8")); P = spec["procedure"]; C = spec["context"]
    gate_cfg = GateCfg(**spec["gates"]); registry = TrialRegistry(args.registry)
    out_dir = ROOT / "reports" / spec["name"]; (out_dir / "cache").mkdir(parents=True, exist_ok=True)
    for name, fname in spec["instruments"].items():
        if args.only and name != args.only: continue
        df15 = load_mt5_csv(ROOT / "data" / "real" / fname)          # horloge eu_dst (défaut)
        for tf, tfc in spec["timeframes"].items():
            if args.tf and tf != args.tf: continue
            if tfc.get("file"):                                          # timeframe fin : export dédié requis
                path = ROOT / "data" / "real" / tfc["file"]
                if not path.exists():
                    print(f"[{name}_{tf}] fichier absent ({tfc['file']}) : export MT5 requis (scripts/export_mt5.py) — ignoré", flush=True)
                    continue
                df_tf = load_mt5_csv(path)
                research, _locked = split_locked(df_tf, tfc.get("lock_months", spec["lock_months"]), spec["lock_min_frac"])
                measured = costs_from_frame(df_tf)
            else:
                research, _locked = split_locked(df15, tfc.get("lock_months", spec["lock_months"]), spec["lock_min_frac"])
                measured = costs_from_frame(df15)
            base = research if tfc.get("rule") is None else resample_base(research, tfc["rule"])
            s = build_settings(spec, name, measured, base).with_overrides({"backtest.max_hold_bars": tfc["max_hold_bars"]})
            tag = f"{name}_{tf}"
            print(f"[{tag}] {len(base)} barres · scores…", flush=True)
            bull, bear = cached_scores(base, s, out_dir / "cache")
            lab = compute_labels(base, s)
            st = mtf_bias(base, tuple(tfc.get("context_rules", C["rules"])), fast=C["fast"], slow=C["slow"], band=C["band"])
            state = st.to_numpy().astype(int)
            n = len(base); k = int(P["train_frac"] * n); purge = lab.purge_bars(s)
            t = np.arange(n); tr = t < k - purge; va = t >= k + purge
            model = fit_stratified(bull, bear, lab.long_r, lab.short_r, state, tr, P["zone_min_score"], P["min_support"], P["margin_R"],
                                   {"instrument": name, "timeframe": tf, "split_index": k, "purge": purge})
            model.save(out_dir / f"{tag}_model.json")
            diag = {**cell_table(bull, lab.long_r, state, tr, va, "long"), **cell_table(bear, lab.short_r, state, tr, va, "short")}
            share = {key: len(c.x) for key, c in model.curves.items()}
            warm = s.backtest.warmup_bars
            valid_df = base.iloc[max(0, k - warm):]
            eng = MTFCalibratedSignalEngine(s, model, st)
            ev = evaluate_research(valid_df, s, registry, gate_cfg, eng, spec_extra={"model": model.hash(), "name": spec["name"], "tf": tf})
            res = {"instrument": name, "timeframe": tf, "spec": spec["name"], "model_hash": model.hash(), "cells": diag,
                   "curve_points": share, "state_share_train": {str(v): float((state[tr] == v).mean()) for v in (-1, 0, 1)},
                   "evaluation": ev.to_dict()}
            (out_dir / f"{tag}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
            print(f"[{tag}] verdict={ev.verdict} | {ev.metrics['n_trades']} trades | E={ev.metrics['expectancy_R']:.3f}R | PF={ev.metrics['profit_factor']:.2f} | essais={ev.n_trials}", flush=True)
            aligned = [("long|état+1", diag["long|état+1|score>=0.65"]), ("short|état-1", diag["short|état-1|score>=0.65"])]
            counter = [("long|état-1", diag["long|état-1|score>=0.65"]), ("short|état+1", diag["short|état+1|score>=0.65"])]
            print("        alignés (score>=0.65):", [(a, c["n_train"], c["E_train"], c["n_valid"], c["E_valid"]) for a, c in aligned], flush=True)
            print("        contre-tendance      :", [(a, c["n_train"], c["E_train"], c["n_valid"], c["E_valid"]) for a, c in counter], flush=True)


if __name__ == "__main__":
    main()
