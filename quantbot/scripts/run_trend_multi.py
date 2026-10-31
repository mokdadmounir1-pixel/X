"""Exécute specs/trend_multi_v1.json : suivi de tendance multi-actifs (stratégie 3 du cahier). UN essai compté (registre chaîné). Verdict : NON_CONCLUANT / FAIL / CANDIDAT (jamais PASS). Aucun ordre.

    python scripts/run_trend_multi.py specs/trend_multi_v1.json

Les `lock_months` derniers mois ne sont JAMAIS lus. Données : barres H1 de data/live (historique long) ou à défaut M15 ; heure du courtier reconstruite depuis time_broker_epoch.
Swaps NON CONNUS : exclus et déclarés. Commission : HYPOTHÈSE déclarée dans la spec.
"""
import argparse, hashlib, json, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.data.mt5 import load_mt5_csv
from quantbot.lab.registry import TrialRegistry, canonical_hash
from quantbot.lab.stats import deflated_sharpe, sign_flip_pvalue
from quantbot.stat import trend_multi as tm


def load_market(root: Path, sym: str, files: list) -> pd.DataFrame | None:
    for rel in files:
        f = root / rel
        if f.exists():
            return load_mt5_csv(f)
    return None


def main(argv=None) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("spec"); ap.add_argument("--root", default=str(ROOT)); args = ap.parse_args(argv)
    root = Path(args.root); spec = json.loads(Path(args.spec).read_text(encoding="utf-8")); g = spec["gates"]; reg = TrialRegistry(root / "reports" / "registry.jsonl")
    daily, costs, used, skipped = {}, {}, {}, {}
    for sym, cfg in spec["markets"].items():
        df = load_market(root, sym, cfg["files"])
        if df is None:
            skipped[sym] = "fichier absent"; continue
        d = tm.daily_ohlc(df.iloc[:-1] if len(df) else df)                          # le dernier jour (incomplet) est écarté
        if len(d) < spec["min_days"]:
            skipped[sym] = f"historique trop court ({len(d)} jours < {spec['min_days']})"; continue
        daily[sym] = d; c = cfg["cost"]; costs[sym] = c["spread_frac"] / 2.0 + c["fee_rate"] + c["slippage"]; used[sym] = {"days": int(len(d)), "first": str(d.index[0].date()), "last": str(d.index[-1].date())}
    if len(daily) < spec["min_markets"]:
        print(f"NON CONCLUANT : {len(daily)} marchés exploitables < {spec['min_markets']} (écartés : {skipped})"); return 2
    end = max(d.index[-1] for d in daily.values()); cut = end - pd.DateOffset(months=int(spec["lock_months"]))      # tranche verrouillée jamais lue
    daily = {k: d[d.index < cut] for k, d in daily.items()}
    sim = tm.simulate(daily, costs, spec["params"]); ret = sim["returns"]; base = tm.basket_buy_hold(daily, spec["params"])
    m, mb = tm.metrics(ret), tm.metrics(base); r = ret[ret.index >= ret[ret != 0].index[0]] if (ret != 0).any() else ret
    sr = float(r.mean() / r.std()) if len(r) > 5 and r.std() > 0 else 0.0
    reg.record_trial(canonical_hash({"spec": spec["name"], "params": spec["params"], "markets": sorted(daily)}), hashlib.sha256(pd.concat(daily, axis=1).to_csv().encode()).hexdigest(), sr, int(len(r)), strategy="trend_multi", symbol="PORTFOLIO")
    p = sign_flip_pvalue(r.to_numpy()) if len(r) > 20 else 1.0; dsr = deflated_sharpe(r.to_numpy(), reg.n_trials(), reg.var_sharpe()) if len(r) > 20 else 0.0
    corr = float(np.corrcoef(r.reindex(base.index).fillna(0.0), base.fillna(0.0))[0, 1]) if len(r) > 20 else None
    verdict = "NON_CONCLUANT" if (m["sharpe"] is None or m["n_days"] < g["min_days"]) else "FAIL" if (m["sharpe"] <= (mb["sharpe"] or 0) or m["ann_return"] <= 0 or p > g["sign_flip_alpha"] or dsr < g["dsr_min"]) else "CANDIDAT"
    out = {"spec": spec["name"], "markets": used, "skipped": skipped, "metrics": m, "basket_long_only": mb, "corr_to_basket": corr, "sign_flip_p": p, "dsr": dsr, "n_trials": reg.n_trials(),
           "costs_paid_total": float(sim["costs_paid"].sum()), "contribution": sim["contribution"], "verdict": verdict, "swaps": "NON CONNUS : exclus"}
    d = root / "reports" / spec["name"]; d.mkdir(parents=True, exist_ok=True); (d / "result.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("metrics", "basket_long_only", "corr_to_basket", "sign_flip_p", "dsr", "verdict")}, indent=1, default=str)); print(f"Essais comptés : {reg.n_trials()}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
