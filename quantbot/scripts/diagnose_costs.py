"""DIAGNOSTIC (pas un essai) : espérance brute vs nette de coûts de la spec préenregistrée.
Ne sert qu'à comprendre POURQUOI un verdict est ce qu'il est ; ne doit jamais servir à choisir un réglage."""
import json, sys
from multiprocessing import Pool
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from baseline_real import build_settings
from quantbot.backtest.engine import Backtester
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.lab.locked import split_locked

def run(name):
    spec = json.loads((ROOT / "specs/baseline_v0.json").read_text(encoding="utf-8"))
    df = load_mt5_csv(ROOT / "data/real" / spec["instruments"][name])
    research, _ = split_locked(df, spec["lock_months"], spec["lock_min_frac"])
    s = build_settings(spec, name, costs_from_frame(df), research)
    net = Backtester(s).run(research)
    free = Backtester(s.with_overrides({"execution.fee_rate": 0.0, "execution.slippage": 0.0, "execution.spread": 0.0})).run(research)
    rn, rf = np.array([t.r_nominal for t in net.trades]), np.array([t.r_nominal for t in free.trades])
    stop_pct = np.median([abs(t.entry - (t.exit if t.reason == "stop_loss" else t.entry)) / t.entry for t in net.trades if t.reason == "stop_loss"] or [np.nan]) * 100
    reasons = {k: int(sum(t.reason == k for t in net.trades)) for k in ("stop_loss", "take_profit", "max_hold", "stop_gap", "data_gap")}
    return {"instrument": name, "n": len(rn), "E_net_R": round(float(rn.mean()), 4), "E_gross_R_sans_couts": round(float(rf.mean()), 4),
            "cout_moyen_R": round(float(rf.mean() - rn.mean()), 4), "win_rate_net": round(float((rn > 0).mean()), 3),
            "stop_median_pct_prix": round(float(stop_pct), 4), "sorties": reasons}

if __name__ == "__main__":
    with Pool(3) as p:
        out = p.map(run, ["EURUSD", "XAUUSD", "USTEC"])
    for o in out: print(json.dumps(o, ensure_ascii=False))
