"""Première évaluation RÉELLE d'une spec préenregistrée (specs/*.json) sur la partie RECHERCHE des données.

La période verrouillée n'est lue QUE avec --locked (une seule fois par spec, enregistré dans le registre).
Usage : python scripts/baseline_real.py specs/baseline_v0.json [--only EURUSD] [--locked]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantbot.config import Settings
from quantbot.data.mt5 import costs_from_frame, find_holes, leverage_cap_from_gaps, load_mt5_csv
from quantbot.lab.gates import GateCfg
from quantbot.lab.locked import split_locked
from quantbot.lab.pipeline import data_hash, evaluate_locked, evaluate_research, spec_hash
from quantbot.lab.registry import TrialRegistry
from quantbot.lab.specs import build_settings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--only")
    ap.add_argument("--locked", action="store_true", help="lit la période verrouillée (UNE fois par spec)")
    ap.add_argument("--data-dir", default=str(ROOT / "data" / "real"))
    ap.add_argument("--registry", default=str(ROOT / "reports" / "registry.jsonl"))
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    gate_cfg = GateCfg(**spec["gates"])
    registry = TrialRegistry(args.registry)
    out_dir = ROOT / "reports" / spec["name"]
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, fname in spec["instruments"].items():
        if args.only and name != args.only:
            continue
        df = load_mt5_csv(Path(args.data_dir) / fname)
        measured = costs_from_frame(df)
        research, locked = split_locked(df, spec["lock_months"], spec["lock_min_frac"])
        settings = build_settings(spec, name, measured, research)
        print(f"[{name}] recherche {research.index[0]} -> {research.index[-1]} ({len(research)} barres), "
              f"verrou dès {locked.lock_start}, trous {len(find_holes(df, settings.backtest.max_gap_hours))}", flush=True)
        ev = evaluate_research(research, settings, registry, gate_cfg)
        result = {"instrument": name, "spec": spec["name"], "evaluation": ev.to_dict(),
                  "costs_used": {"spread": settings.execution.spread, "fee_rate": settings.execution.fee_rate,
                                 "slippage": settings.execution.slippage, "measured": measured,
                                 "max_leverage": settings.risk.max_leverage},
                  "holes": find_holes(df, settings.backtest.max_gap_hours)}
        if args.locked:
            result["locked"] = evaluate_locked(locked, settings, registry, gate_cfg)
        (out_dir / f"{name}.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        g = {x.name: ("OK" if x.ok else "ÉCHEC") for x in ev.gates}
        print(f"[{name}] verdict={ev.verdict} | {ev.metrics['n_trades']} trades | E={ev.metrics['expectancy_R']:.3f}R | "
              f"PF={ev.metrics['profit_factor']:.2f} | essais cumulés={ev.n_trials}\n        {ev.reason}\n        {g}", flush=True)


if __name__ == "__main__":
    main()
