"""Phase 2 : calibration score -> espérance nette (apprentissage) puis évaluation sur la validation (hors échantillon).

Usage : python scripts/run_v2.py specs/v2_calibrated.json [--only EURUSD]
La période verrouillée n'est jamais lue ici. Un essai est enregistré par instrument.
"""
import argparse, hashlib, json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from baseline_real import build_settings
from quantbot.core.calibration import CalibrationModel, fit_curve
from quantbot.core.labels import compute_labels
from quantbot.core.scores import compute_scores
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.lab.gates import GateCfg
from quantbot.lab.locked import split_locked
from quantbot.lab.pipeline import data_hash, evaluate_research
from quantbot.lab.registry import TrialRegistry
from quantbot.signals.calibrated import CalibratedSignalEngine


def cached_scores(research, settings, cache_dir):
    key = hashlib.sha256((data_hash(research) + json.dumps({k: v for k, v in settings.to_dict().items()
                          if k in ("tolerance", "detection", "signals")}, sort_keys=True)).encode()).hexdigest()[:20]
    f = cache_dir / f"scores_{key}.npz"
    if f.exists():
        z = np.load(f); return z["bull"], z["bear"]
    bull, bear = compute_scores(research, settings)
    np.savez(f, bull=bull, bear=bear)
    return bull, bear


def table(score, y_tr, y_va, tr, va, edges):
    rows = []
    for a, b in zip(edges[:-1], edges[1:]):
        mt, mv = tr & (score >= a) & (score < b), va & (score >= a) & (score < b)
        rows.append({"score": f"[{a:.2f},{b:.2f})", "n_train": int(mt.sum()), "E_train": round(float(np.nanmean(y_tr[mt])), 4) if mt.any() else None,
                     "n_valid": int(mv.sum()), "E_valid": round(float(np.nanmean(y_va[mv])), 4) if mv.any() else None})
    return rows


def placebo_share(score, y, tr, zone, support, margin, seeds=5, block=100):
    shares = []
    idx = np.flatnonzero(tr & np.isfinite(y))
    for sd in range(seeds):
        rng = np.random.default_rng(sd)
        nb = int(np.ceil(len(idx) / block)); order = rng.permutation(nb)
        yp = np.concatenate([y[idx][b * block:(b + 1) * block] for b in order])[:len(idx)]
        c = fit_curve(score[idx], yp, zone, support)
        pred = c.predict_many(score[idx]); ok = np.isfinite(pred)
        shares.append(float((pred[ok] > margin).sum() / max(len(idx), 1)))
    return float(np.mean(shares))


def main():
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--only")
    ap.add_argument("--registry", default=str(ROOT / "reports" / "registry.jsonl"))
    args = ap.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8")); P = spec["procedure"]
    gate_cfg = GateCfg(**spec["gates"]); registry = TrialRegistry(args.registry)
    out_dir = ROOT / "reports" / spec["name"]; (out_dir / "cache").mkdir(parents=True, exist_ok=True)
    for name, fname in spec["instruments"].items():
        if args.only and name != args.only: continue
        df = load_mt5_csv(ROOT / "data" / "real" / fname)
        research, _locked = split_locked(df, spec["lock_months"], spec["lock_min_frac"])
        s = build_settings(spec, name, costs_from_frame(df), research)
        print(f"[{name}] scores…", flush=True)
        bull, bear = cached_scores(research, s, out_dir / "cache")
        lab = compute_labels(research, s)
        n = len(research); k = int(P["train_frac"] * n); purge = lab.purge_bars(s)
        t = np.arange(n); tr = t < k - purge; va = t >= k + purge
        zone, support, margin = P["zone_min_score"], P["min_support"], P["margin_R"]
        model = CalibrationModel(fit_curve(bull[tr], lab.long_r[tr], zone, support),
                                 fit_curve(bear[tr], lab.short_r[tr], zone, support), margin,
                                 {"instrument": name, "train_bars": int(tr.sum()), "split_index": k, "purge": purge})
        model.save(out_dir / f"{name}_model.json")
        edges = np.array([zone, 0.45, 0.55, 0.65, 0.75, 0.85, 1.0001])
        diag = {"long": table(bull, lab.long_r, lab.long_r, tr, va, edges), "short": table(bear, lab.short_r, lab.short_r, tr, va, edges),
                "placebo_share_above_margin": {"long": placebo_share(bull, lab.long_r, tr, zone, support, margin),
                                               "short": placebo_share(bear, lab.short_r, tr, zone, support, margin)},
                "curve_points": {"long": len(model.long.x), "short": len(model.short.x),
                                 "n_train_long": model.long.n_train, "n_train_short": model.short.n_train}}
        pl, ps = model.long.predict_many(bull[tr]), model.short.predict_many(bear[tr])
        diag["share_train_bars_tradable"] = {"long": float(np.nanmean(pl > margin)) if np.isfinite(pl).any() else 0.0,
                                             "short": float(np.nanmean(ps > margin)) if np.isfinite(ps).any() else 0.0}
        warm = s.backtest.warmup_bars
        valid_df = research.iloc[max(0, k - warm):]
        eng = CalibratedSignalEngine(s, model)
        print(f"[{name}] modèle {model.hash()[:10]} | long n={model.long.n_train} pts={len(model.long.x)} | short n={model.short.n_train} pts={len(model.short.x)} "
              f"| évaluation sur {len(valid_df)} barres…", flush=True)
        ev = evaluate_research(valid_df, s, registry, gate_cfg, eng, spec_extra={"model": model.hash(), "name": spec["name"]})
        res = {"instrument": name, "spec": spec["name"], "model_hash": model.hash(), "diagnostics": diag, "evaluation": ev.to_dict()}
        (out_dir / f"{name}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        print(f"[{name}] verdict={ev.verdict} | {ev.metrics['n_trades']} trades | E={ev.metrics['expectancy_R']:.3f}R | PF={ev.metrics['profit_factor']:.2f} | "
              f"essais cumulés={ev.n_trials}\n        {ev.reason}", flush=True)
        for side in ("long", "short"):
            print(f"        {side}: ", [(r['score'], r['n_train'], r['E_train'], r['n_valid'], r['E_valid']) for r in diag[side]], flush=True)
        print(f"        placebo (part de barres > marge par pur hasard): {diag['placebo_share_above_margin']} | tradable en train: {diag['share_train_bars_tradable']}", flush=True)


if __name__ == "__main__":
    main()
