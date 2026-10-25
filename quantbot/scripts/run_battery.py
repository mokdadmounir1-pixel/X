"""Batterie d'hypothèses documentées (specs/battery_v1.json) sur la période de RECHERCHE : verdict après correction de multiplicité.

Usage : python scripts/run_battery.py specs/battery_v1.json     (la période verrouillée n'est jamais lue)
"""
import argparse, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.lab import battery as bt
from quantbot.lab import stats as st
from quantbot.lab.locked import split_locked
from quantbot.lab.pipeline import data_hash
from quantbot.lab.registry import TrialRegistry, canonical_hash


def cost_rt(spec, name, measured):
    c = spec["costs"][name]
    spread = c["spread_frac"] if c.get("spread_frac") is not None else measured["spread_frac"]
    if spread is None:
        raise SystemExit(f"{name}: spread inconnu : refus (un coût nul n'est jamais supposé)")
    return spread + 2.0 * (c["fee_rate"] + c["slippage"])


def main():
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--registry", default=str(ROOT / "reports" / "registry.jsonl"))
    args = ap.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8")); R = spec["rules"]
    reg = TrialRegistry(args.registry); out_dir = ROOT / "reports" / spec["name"]; out_dir.mkdir(parents=True, exist_ok=True)
    spec_h = canonical_hash({k: spec[k] for k in ("hypotheses", "costs", "rules")})
    results, nets = {}, {}
    for name, fname in spec["instruments"].items():
        df = load_mt5_csv(ROOT / "data" / "real" / fname)
        research, _locked = split_locked(df, spec["lock_months"], spec["lock_min_frac"])
        p = bt.session_prices(research); c = cost_rt(spec, name, costs_from_frame(df)); dh = data_hash(research)
        for hyp, h in spec["hypotheses"].items():
            if name not in h["instruments"]:
                continue
            res = bt.HYPOTHESES[hyp](p, c, **h.get("params", {}))
            res2 = bt.HYPOTHESES[hyp](p, 2 * c, **h.get("params", {}))
            s = bt.summarize(res.net, res.bh)
            s["mean_bps_costs_x2"] = float(res2.net.mean() * 1e4); s["cost_rt_bps"] = c * 1e4; s["n_trades"] = res.n_trades
            sr, sk, ku, n = st.sharpe_moments(res.net.to_numpy())
            reg.record_trial(canonical_hash([spec_h, name, hyp]), dh, sr, n)
            results[(name, hyp)] = s; nets[(name, hyp)] = res.net
    keys = list(results)
    idx = sorted(set().union(*[nets[k].index for k in keys]))
    mat = np.column_stack([nets[k].reindex(idx).fillna(0.0).to_numpy() for k in keys])
    rc = st.reality_check(mat, B=R["reality_check"]["B"], mean_block=R["reality_check"]["mean_block"])
    n_trials, var_sr = reg.n_trials(), reg.var_sharpe()
    rows = []
    for k in keys:
        s = results[k]; x = nets[k].to_numpy()
        s["dsr"] = st.deflated_sharpe(x, n_trials, var_sr)
        both_halves = s["mean_first_half_bps"] > 0 and s["mean_second_half_bps"] > 0
        survivor = rc["p"] is not None and rc["p"] < 0.10 and s["t_nw"] > 2.0 and both_halves and s["mean_bps_costs_x2"] > 0 and s["bh_t_alpha"] > 2.0
        watch = rc["p"] is not None and rc["p"] < 0.20 and both_halves and s["mean_bps_costs_x2"] > 0
        s["verdict"] = "SURVIVANT" if survivor else ("WATCH" if watch else "REJETÉ")
        rows.append((k, s))
        (out_dir / f"{k[0]}_{k[1]}.json").write_text(json.dumps({"instrument": k[0], "hypothesis": k[1], **s}, indent=1), encoding="utf-8")
    summary = {"reality_check": rc, "n_trials_registry": n_trials, "n_hypotheses": len(keys), "days": len(idx),
               "results": {f"{k[0]}|{k[1]}": s for k, s in rows}}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"Reality Check (14 hypothèses, {len(idx)} jours) : p = {rc['p']} | meilleure : {keys[rc['best']] if rc.get('best') is not None else None} | essais cumulés = {n_trials}")
    print(f"{'instrument':8s} {'hypothèse':18s} {'jours':>5s} {'moy bps':>8s} {'x2 coûts':>9s} {'Sharpe':>7s} {'t_NW':>6s} {'1/2':>7s} {'2/2':>7s} {'alpha t':>8s} {'DSR':>5s}  verdict")
    for k, s in sorted(rows, key=lambda r: -r[1]["t_nw"]):
        print(f"{k[0]:8s} {k[1]:18s} {s['n_days']:5d} {s['mean_bps']:8.2f} {s['mean_bps_costs_x2']:9.2f} {s['sharpe_annual']:7.2f} {s['t_nw']:6.2f} {s['mean_first_half_bps']:7.2f} {s['mean_second_half_bps']:7.2f} {s['bh_t_alpha']:8.2f} {s['dsr']:5.2f}  {s['verdict']}")


if __name__ == "__main__":
    main()
