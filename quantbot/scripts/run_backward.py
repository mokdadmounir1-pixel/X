"""Backtest en ARRIÈRE : les stratégies FIGÉES (specs/inst_strategies_v1.json, paramètres inchangés) sur les années qui PRÉCÈDENT
la période de recherche utilisée jusqu'ici. Ces années n'ont été vues par aucun essai : c'est un test hors échantillon sans réglage.

    python scripts/run_backward.py specs/backward_v1.json [--inst XAUUSD] [--only vwap]

Lit uniquement le segment strictement antérieur au début des exports actuels (data/real) ; la période verrouillée n'est jamais touchée.
"""
import argparse, json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.backtest.engine import Backtester
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.lab.gates import GateCfg
from quantbot.lab.pipeline import evaluate_research
from quantbot.lab.registry import TrialRegistry, canonical_hash
from quantbot.lab.specs import build_settings
from quantbot.strategies import amd, fvg, orb, smc, vwap
from quantbot.strategies.events import EventSignalEngine


def gen(name, scfg, df):
    if name == "amd": return amd.events(df, {**amd.PARAMS, **{k: tuple(v) if isinstance(v, list) else v for k, v in scfg["params"].items()}})
    if name == "vwap": return vwap.events(df, scfg["params"])
    if name == "orb": return orb.events(df, scfg["params"])
    if name.startswith("smc"): return smc.events(df, scfg["rule"], scfg["params"])
    return fvg.events(df, scfg["rule"], scfg["params"])


def segment_before(deep, original_start, min_bars):
    """Barres strictement antérieures au début de la période déjà utilisée ; None si le segment est trop court pour juger."""
    seg = deep[deep.index < original_start]
    return seg if len(seg) >= min_bars else None


def main():
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--only"); ap.add_argument("--inst")
    ap.add_argument("--registry", default=str(ROOT / "reports" / "registry.jsonl"))
    args = ap.parse_args()
    bw = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    base = json.loads((ROOT / bw["base_spec"]).read_text(encoding="utf-8")); gate_cfg = GateCfg(**base["gates"]); reg = TrialRegistry(args.registry)
    out = ROOT / "reports" / bw["name"]; out.mkdir(parents=True, exist_ok=True)
    for inst, fname in base["instruments"].items():
        if args.inst and inst != args.inst: continue
        deep_path = ROOT / bw["deep_dir"] / fname
        if not deep_path.is_file():
            print(f"[{inst}] SAUTÉ : {deep_path} absent (exporter l'historique profond, voir docs/prompts/chatgpt_c6_deep_history.md)"); continue
        original_start = load_mt5_csv(ROOT / "data" / "real" / fname).index[0]
        seg = segment_before(load_mt5_csv(deep_path), original_start, bw["min_bars"])
        if seg is None:
            print(f"[{inst}] SAUTÉ : moins de {bw['min_bars']} barres avant {original_start} (historique du courtier insuffisant)"); continue
        measured = costs_from_frame(seg)
        for name, scfg in base["strategies"].items():
            if inst not in scfg["instruments"] or (args.only and name != args.only): continue
            s = build_settings(base, inst, measured, seg).with_overrides({"backtest.max_hold_bars": scfg["max_hold_bars"]})
            events = gen(name, scfg, seg)
            ev = evaluate_research(seg, s, reg, gate_cfg, EventSignalEngine(s, events),
                                   spec_extra={"strategy": name, "params": canonical_hash(scfg["params"]), "segment": "backward_v1"})
            res = {"instrument": inst, "strategy": name, "label": scfg["label"], "segment": {"start": str(seg.index[0]), "end": str(seg.index[-1]), "bars": len(seg)},
                   "n_events": len(events), "buy_hold_pct": round(float(seg.close.iloc[-1] / seg.close.iloc[0] - 1) * 100, 1),
                   "evaluation": ev.to_dict(), "costs_used": {"spread": s.execution.spread, "max_leverage": s.risk.max_leverage}}
            (out / f"{inst}_{name}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
            m = ev.metrics
            print(f"[{inst} {name:7s}] {str(seg.index[0])[:10]}→{str(seg.index[-1])[:10]} {ev.verdict:5s} | trades={m['n_trades']:5d} E={m['expectancy_R']:+.3f}R PF={m['profit_factor']:.2f} "
                  f"worst={m.get('worst_trade_R', 0):.2f} buy&hold={res['buy_hold_pct']:+.1f}% | échecs: {[g.name for g in ev.gates if not g.ok]} | essais={ev.n_trials}", flush=True)


if __name__ == "__main__":
    main()
