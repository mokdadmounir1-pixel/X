"""Exécute specs/ml_v1.json : LightGBM walk-forward purgé sur les exports MT5. Un essai compté par instrument (registre chaîné).

    python scripts/run_ml.py specs/ml_v1.json

Les `lock_months` derniers mois ne sont JAMAIS lus. Verdict : NON_CONCLUANT / FAIL / CANDIDAT (jamais PASS). Aucun ordre.
"""
import argparse, hashlib, json, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.data.mt5 import load_mt5_csv
from quantbot.lab.registry import TrialRegistry, canonical_hash
from quantbot.lab.stats import deflated_sharpe, sign_flip_pvalue
from quantbot.ml.features import build_features
from quantbot.ml.model import MLParams, auc, make_labels, simulate, walk_forward_proba


def main(argv=None) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("spec"); ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv); root = Path(args.root); spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    reg = TrialRegistry(root / "reports" / "registry.jsonl"); out = {"spec": spec["name"], "instruments": {}}; g = spec["gates"]
    for sym, rel in spec["instruments"].items():
        df = load_mt5_csv(root / rel); df = df[df.index <= df.index[-1] - pd.DateOffset(months=int(spec["lock_months"]))]   # tranche verrouillée non lue
        p = MLParams(**spec["ml"], cost_frac=spec["costs"]["cost_frac"][sym])
        X = build_features(df, spec["features"]["frac_diff_d"], spec["features"]["frac_diff_thresh"])
        y, le = make_labels(df.close.to_numpy(float), p.horizon)
        proba, log = walk_forward_proba(X, y, le, p); trades = simulate(df, proba, p); r = np.array([t["r"] for t in trades])
        ok = ~np.isnan(proba) & (y >= 0)
        res = {"bars": int(len(df)), "start": str(df.index[0]), "end": str(df.index[-1]), "oos_auc": auc(y[ok], proba[ok]) if ok.any() else None,
               "purged_cv_auc_mean": float(np.nanmean([x["purged_cv_auc"] for x in log])) if log else None, "refits": len(log),
               "n_trades": int(len(r)), "mean_r": float(r.mean()) if len(r) else 0.0, "total_r": float(r.sum()), "win_rate": float((r > 0).mean()) if len(r) else 0.0}
        sr = float(r.mean() / r.std(ddof=1)) if len(r) > 2 and r.std(ddof=1) > 0 else 0.0
        reg.record_trial(canonical_hash({"spec": spec["name"], "symbol": sym, "ml": spec["ml"], "features": spec["features"]}), hashlib.sha256(df.to_csv().encode()).hexdigest(), sr, len(r), strategy="ml_lgbm", symbol=sym)
        res["sign_flip_p"] = sign_flip_pvalue(r) if len(r) else 1.0
        res["dsr"] = deflated_sharpe(r, reg.n_trials(), reg.var_sharpe()) if len(r) else 0.0
        res["verdict"] = ("NON_CONCLUANT" if len(r) < g["min_trades"] else
                          "FAIL" if (res["mean_r"] <= 0 or res["sign_flip_p"] > g["sign_flip_alpha"] or res["dsr"] < g["dsr_min"]) else "CANDIDAT")
        out["instruments"][sym] = res
        print(f"{sym}: AUC OOS {res['oos_auc']}, {res['n_trades']} trades, R moyen {res['mean_r']:+.3f}, p {res['sign_flip_p']:.3f}, DSR {res['dsr']:.2f} -> {res['verdict']}")
    d = root / "reports" / spec["name"]; d.mkdir(parents=True, exist_ok=True); (d / "result.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"Essais comptés : {reg.n_trials()}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
