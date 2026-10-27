"""Exécute specs/rl_v1.json : Q-learning tabulaire en walk-forward strict (entraînement passé, test suivant, jamais l'inverse). UN essai compté. Verdict : NON_CONCLUANT / FAIL / CANDIDAT (jamais PASS). Aucun ordre.

    python scripts/run_rl.py specs/rl_v1.json
"""
import argparse, hashlib, json, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.data.mt5 import load_mt5_csv
from quantbot.lab.registry import TrialRegistry, canonical_hash
from quantbot.ml.rl_agent import walk_forward


def main(argv=None) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("spec"); ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv); root = Path(args.root); spec = json.loads(Path(args.spec).read_text(encoding="utf-8")); reg = TrialRegistry(root / "reports" / "registry.jsonl"); out = {"spec": spec["name"], "instruments": {}}
    for sym, rel in spec["instruments"].items():
        df = load_mt5_csv(root / rel); df = df[df.index <= df.index[-1] - pd.DateOffset(months=int(spec["lock_months"]))]       # tranche verrouillée non lue
        res = walk_forward(df, **spec["rl"]); res["bars"] = int(len(df))
        reg.record_trial(canonical_hash({"spec": spec["name"], "symbol": sym, "rl": spec["rl"]}), hashlib.sha256(df.to_csv().encode()).hexdigest(), res.get("oos_sharpe_per_bar", 0.0), int(res.get("n_windows", 0)), strategy="rl_qlearning", symbol=sym)
        res["verdict"] = "FAIL" if (res["oos_sum_atr"] <= 0 or res["oos_sum_atr"] <= res["buy_hold_sum_atr"]) else "CANDIDAT"
        out["instruments"][sym] = res; print(f"{sym}: {res}")
    d = root / "reports" / spec["name"]; d.mkdir(parents=True, exist_ok=True); (d / "result.json").write_text(json.dumps(out, indent=1), encoding="utf-8"); print(f"Essais comptés : {reg.n_trials()}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
