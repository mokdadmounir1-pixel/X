"""Exécute specs/pairs_v1.json sur les CSV exportés (scripts/export_coinbase.py). Un essai compté par variante de coûts (registre chaîné).

    python scripts/run_pairs.py specs/pairs_v1.json

Les `lock_months` derniers mois ne sont JAMAIS lus. Verdict : NON_CONCLUANT / FAIL / CANDIDAT (jamais PASS : le forward et le DSR global restent exigés).
"""
import argparse, hashlib, json, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.data.coinbase import load_utc_csv
from quantbot.lab.registry import TrialRegistry, canonical_hash
from quantbot.stat.pairs import PairParams, simulate_pair


def load_pair(spec: dict, root: Path) -> pd.DataFrame:
    a_name, b_name = spec["legs"]; tf = spec["timeframe"]
    a = load_utc_csv(root / spec["data_dir"] / f"{a_name}_{tf}.csv"); b = load_utc_csv(root / spec["data_dir"] / f"{b_name}_{tf}.csv")
    df = a[["open", "close"]].join(b[["open", "close"]], how="inner", lsuffix="_a", rsuffix="_b").dropna()
    cutoff = df.index[-1] - pd.DateOffset(months=int(spec["lock_months"]))
    return df[df.index <= cutoff]                     # la tranche verrouillée n'est pas lue


def stats(trades: list[dict]) -> dict:
    r = np.array([t["r"] for t in trades]); n = len(r)
    return {"n_trades": n, "mean_r": float(r.mean()) if n else 0.0, "total_r": float(r.sum()), "win_rate": float((r > 0).mean()) if n else 0.0,
            "per_trade_sharpe": float(r.mean() / r.std(ddof=1)) if n > 2 and r.std(ddof=1) > 0 else 0.0,
            "reasons": {k: int(sum(1 for t in trades if t["reason"] == k)) for k in {t["reason"] for t in trades}}}


def null_p(df: pd.DataFrame, p: PairParams, observed_total: float, n_shifts: int, min_shift: int) -> dict:
    n = len(df); rng = np.random.default_rng(12345); totals = []
    for s in rng.integers(min_shift, max(min_shift + 1, n - min_shift), size=n_shifts):
        bo, bc = np.roll(df.open_b.to_numpy(), int(s)), np.roll(df.close_b.to_numpy(), int(s))
        totals.append(sum(t["r"] for t in simulate_pair(df.open_a, df.close_a, bo, bc, p)))
    totals = np.array(totals)
    return {"null_mean_total_r": float(totals.mean()), "p_value": float((1 + (totals >= observed_total).sum()) / (1 + len(totals)))}


def verdict(st: dict, nl: dict) -> str:
    if st["n_trades"] < 100:
        return "NON_CONCLUANT"
    return "FAIL" if (st["mean_r"] <= 0 or nl["p_value"] > 0.05) else "CANDIDAT"


def main(argv=None) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("spec"); ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv); root = Path(args.root)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8")); df = load_pair(spec, root)
    data_hash = hashlib.sha256(df.to_csv().encode()).hexdigest()
    reg = TrialRegistry(root / "reports" / "registry.jsonl"); out = {"spec": spec["name"], "bars": int(len(df)), "start": str(df.index[0]), "end": str(df.index[-1]), "variants": {}}
    for name, v in spec["variants"].items():
        p = PairParams(**spec["params"], cost_per_leg=v["cost_per_leg"])
        trades = simulate_pair(df.open_a, df.close_a, df.open_b, df.close_b, p); st = stats(trades)
        nl = null_p(df, p, st["total_r"], spec["null"]["n_shifts"], spec["null"]["min_shift_bars"]) if st["n_trades"] else {"p_value": 1.0}
        st.update(nl); st["verdict"] = verdict(st, nl); out["variants"][name] = st
        reg.record_trial(canonical_hash({"spec": spec["name"], "variant": name, "params": spec["params"], "cost": v["cost_per_leg"]}), data_hash, st["per_trade_sharpe"], st["n_trades"], strategy="pairs", variant=name)
        print(f"{name}: {st['n_trades']} trades, R moyen {st['mean_r']:+.3f}, p nul {st['p_value']:.3f} -> {st['verdict']}")
    d = root / "reports" / spec["name"]; d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(json.dumps(out, indent=1), encoding="utf-8"); print(f"Essais comptés : {reg.n_trials()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
