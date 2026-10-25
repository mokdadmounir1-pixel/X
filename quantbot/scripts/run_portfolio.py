"""Exécute specs/portfolio_v1.json : toutes les stratégies à règles figées combinées par des poids causaux. Un essai compté par schéma.

    python scripts/run_portfolio.py specs/portfolio_v1.json            # rejoue toutes les combinaisons (quelques minutes), met le cache à jour
    python scripts/run_portfolio.py specs/portfolio_v1.json --cache    # réutilise reports/portfolio_v1/daily_R.csv
"""
import argparse, hashlib, json, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.backtest.engine import Backtester
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.lab.locked import split_locked
from quantbot.lab.registry import TrialRegistry, canonical_hash
from quantbot.lab.specs import build_settings
from quantbot.lab.stats import deflated_sharpe, sign_flip_pvalue
from quantbot.portfolio.combine import combine, daily_r, diagnostics
from quantbot.strategies.build import events_for
from quantbot.strategies.events import EventSignalEngine


def gather(root: Path, sources: list[str]) -> pd.DataFrame:
    cols = {}
    for src in sources:
        spec = json.loads((root / src).read_text(encoding="utf-8"))
        for inst, fname in spec["instruments"].items():
            df = load_mt5_csv(root / "data" / "real" / fname)
            research, _ = split_locked(df, spec["lock_months"], spec["lock_min_frac"]); measured = costs_from_frame(df)
            for name, scfg in spec["strategies"].items():
                if inst not in scfg["instruments"]:
                    continue
                s = build_settings(spec, inst, measured, research).with_overrides({"backtest.max_hold_bars": scfg["max_hold_bars"]})
                bt = Backtester(s, signal_engine=EventSignalEngine(s, events_for(name, scfg, research))).run(research)
                cols[f"{inst}:{name}"] = daily_r(bt.trades); print(f"  {inst}:{name}: {len(bt.trades)} trades", flush=True)
    R = pd.DataFrame(cols).sort_index()
    return R.reindex(pd.date_range(R.index.min(), R.index.max(), freq="D")).fillna(0.0)


def main(argv=None) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("spec"); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--cache", action="store_true")
    args = ap.parse_args(argv); root = Path(args.root); spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    out_dir = root / "reports" / spec["name"]; out_dir.mkdir(parents=True, exist_ok=True); cache = out_dir / "daily_R.csv"
    if args.cache and cache.exists():
        R = pd.read_csv(cache, index_col=0, parse_dates=True)
    else:
        R = gather(root, spec["sources"]); R.to_csv(cache)
    R = R[R.index.dayofweek < 5]                                   # jours ouvrés
    reg = TrialRegistry(root / "reports" / "registry.jsonl"); g = spec["gates"]; vt = spec["vol_target"]
    dh = hashlib.sha256(R.to_csv().encode()).hexdigest(); res = {"spec": spec["name"], "strategies": list(R.columns), "days": int(len(R)), "schemes": {}}
    for scheme in spec["schemes"]:
        port = combine(R, scheme, 120, vt["target_r_day"], vt["window"], vt["max_scale"]); port = port.iloc[120 + vt["window"]:]     # chauffe des poids et de la vol
        d = diagnostics(R.loc[port.index], port); sr_d = d["mean_r_day"] / d["vol_r_day"] if d["vol_r_day"] > 0 else 0.0
        reg.record_trial(canonical_hash({"spec": spec["name"], "scheme": scheme, "vol": vt}), dh, sr_d, d["days"], strategy="portfolio", scheme=scheme)
        d["sign_flip_p"] = sign_flip_pvalue(port.to_numpy(), block=g["block"]); d["dsr"] = deflated_sharpe(port.to_numpy(), reg.n_trials(), reg.var_sharpe())
        d["verdict"] = ("NON_CONCLUANT" if d["days"] < g["min_days"] else "FAIL" if (d["mean_r_day"] <= 0 or d["sign_flip_p"] > g["sign_flip_alpha"] or d["dsr"] < g["dsr_min"]) else "CANDIDAT")
        res["schemes"][scheme] = d
        print(f"{scheme}: {d['days']} j, R/jour {d['mean_r_day']:+.3f} (repère 0,33), Sharpe {d['sharpe_ann']:+.2f}, corr moy {d['avg_pair_corr']:+.2f}, DD {d['max_dd_r']:.1f} R, p {d['sign_flip_p']:.3f}, DSR {d['dsr']:.2f} -> {d['verdict']}")
    (out_dir / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8"); print(f"Essais comptés : {reg.n_trials()}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
