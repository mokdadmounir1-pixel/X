"""Test CONFIRMATOIRE des filtres SMC choisis sur la première moitié (specs/smc_filt_*_v1.json) : seconde moitié chronologique de la période de recherche, filtrée contre non filtrée, 3 instruments regroupés.
UN essai compté par variante filtrée (registre chaîné). La tranche verrouillée n'est jamais lue.    python scripts/run_smc_filters.py
"""
import hashlib, json, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.backtest.engine import Backtester
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.lab.locked import split_locked
from quantbot.lab.registry import TrialRegistry, canonical_hash
from quantbot.lab.specs import build_settings
from quantbot.lab.stats import sign_flip_pvalue
from quantbot.strategies.build import events_for
from quantbot.strategies.events import EventSignalEngine

PAIRS = [("smc_filt_orig_v1", "smc_m15_f", "smc_orig_v1", "smc_m15"), ("smc_filt_free_v1", "smc_m15_free_f", "smc_free_v1", "smc_m15_free")]
INSTR = ("EURUSD", "XAUUSD", "USTEC")


def run(spec, name, inst, research, mid):
    sc = spec["strategies"][name]; st = build_settings(spec, inst, costs_from_frame(research), research).with_overrides({"backtest.max_hold_bars": sc["max_hold_bars"]})
    evs = [e for e in events_for(name, sc, research) if e.ts >= mid]; seg = research[research.index >= mid]
    res = Backtester(st, 1.0, EventSignalEngine(st, evs)).run(seg); return np.array([t.r_nominal for t in res.trades]), [str(t.entry_time) for t in res.trades]


def stats(r):
    return {"n": int(len(r)), "E_R": float(r.mean()) if len(r) else None, "sum_R": float(r.sum()), "win_rate": float((r > 0).mean()) if len(r) else None,
            "PF": float(r[r > 0].sum() / -r[r < 0].sum()) if (r < 0).any() and (r > 0).any() else None}


def main():
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    reg = TrialRegistry(ROOT / "reports" / "registry.jsonl"); out = {"note": "seconde moitié chronologique de la période de recherche (non vue lors du choix du filtre)", "variants": {}}
    for fspec, fname, ospec, oname in PAIRS:
        sf = json.loads((ROOT / "specs" / f"{fspec}.json").read_text(encoding="utf-8")); so = json.loads((ROOT / "specs" / f"{ospec}.json").read_text(encoding="utf-8")); rf, ro, dh = [], [], hashlib.sha256()
        for inst in INSTR:
            full = load_mt5_csv(ROOT / "data" / "real" / f"{inst}_M15.csv"); research, _ = split_locked(full, sf["lock_months"], sf["lock_min_frac"]); mid = research.index[len(research) // 2]
            dh.update(research[research.index >= mid].to_csv().encode()); a, _ = run(sf, fname, inst, research, mid); b, _ = run(so, oname, inst, research, mid); rf.append(a); ro.append(b)
        rf, ro = np.concatenate(rf), np.concatenate(ro); sr = float(rf.mean() / rf.std()) if len(rf) > 2 and rf.std() > 0 else 0.0
        reg.record_trial(canonical_hash({"spec": sf["name"], "strategy": fname, "filter": sf["strategies"][fname]["entry_filter"]}), dh.hexdigest(), sr, int(len(rf)), strategy=fname, symbol="POOL3")
        verdict = ("NON_CONCLUANT" if len(rf) < 60 else "CONFIRME" if (rf.mean() > ro.mean() and rf.mean() > 0 and sign_flip_pvalue(rf) < 0.10) else "NON_CONFIRME")
        out["variants"][fname] = {"filter": sf["strategies"][fname]["entry_filter"], "filtered": stats(rf), "unfiltered": stats(ro), "uplift_E_R": (float(rf.mean() - ro.mean()) if len(rf) and len(ro) else None), "sign_flip_p_filtered": float(sign_flip_pvalue(rf)) if len(rf) > 5 else None, "verdict": verdict}
        print(fname, json.dumps(out["variants"][fname], default=float))
    out["n_trials"] = reg.n_trials(); (ROOT / "reports" / "smc_filters_v1").mkdir(parents=True, exist_ok=True); (ROOT / "reports" / "smc_filters_v1" / "TEST.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8"); print("Essais comptés :", reg.n_trials())


if __name__ == "__main__":
    main()
