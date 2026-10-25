"""Stratégies à règles explicites (specs/inst_strategies_v1.json) : événements causaux -> moteur unique -> portes. Période de RECHERCHE seulement."""
import argparse, json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.backtest.engine import Backtester
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.lab.gates import GateCfg
from quantbot.lab.locked import split_locked
from quantbot.lab.pipeline import evaluate_research
from quantbot.lab.registry import TrialRegistry, canonical_hash
from quantbot.lab.specs import build_settings
from quantbot.strategies import amd, fvg, orb, smc, vwap
from quantbot.strategies.build import events_for
from quantbot.strategies.events import EventSignalEngine


def gen(name, scfg, df):
    if name.startswith("gq_"): return events_for(name, scfg, df)
    if name == "amd": return amd.events(df, {**amd.PARAMS, **{k: tuple(v) if isinstance(v, list) else v for k, v in scfg["params"].items()}})
    if name == "vwap": return vwap.events(df, scfg["params"])
    if name == "orb": return orb.events(df, scfg["params"])
    if name.startswith("smc"): return smc.events(df, scfg["rule"], scfg["params"])
    return fvg.events(df, scfg["rule"], scfg["params"])


def main():
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--only"); ap.add_argument("--inst")
    ap.add_argument("--registry", default=str(ROOT / "reports" / "registry.jsonl"))
    args = ap.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8")); gate_cfg = GateCfg(**spec["gates"]); reg = TrialRegistry(args.registry)
    out = ROOT / "reports" / spec["name"]; out.mkdir(parents=True, exist_ok=True)
    for inst, fname in spec["instruments"].items():
        if args.inst and inst != args.inst: continue
        df = load_mt5_csv(ROOT / "data" / "real" / fname)
        research, _locked = split_locked(df, spec["lock_months"], spec["lock_min_frac"]); measured = costs_from_frame(df)
        for name, scfg in spec["strategies"].items():
            if inst not in scfg["instruments"] or (args.only and name != args.only): continue
            s = build_settings(spec, inst, measured, research).with_overrides({"backtest.max_hold_bars": scfg["max_hold_bars"]})
            events = gen(name, scfg, research)
            eng = EventSignalEngine(s, events)
            ev = evaluate_research(research, s, reg, gate_cfg, eng, spec_extra={"strategy": name, "params": canonical_hash(scfg["params"])})
            bt = Backtester(s, signal_engine=EventSignalEngine(s, events)).run(research)   # attribution par direction (diagnostic)
            side = {sd: {"n": sum(t.side == sd for t in bt.trades),
                         "E_R": round(float(np.mean([t.r_nominal for t in bt.trades if t.side == sd])), 4) if any(t.side == sd for t in bt.trades) else None}
                    for sd in ("long", "short")}
            res = {"instrument": inst, "strategy": name, "label": scfg["label"], "n_events": len(events), "by_side": side,
                   "buy_hold_research_pct": round(float(research.close.iloc[-1] / research.close.iloc[0] - 1) * 100, 1),
                   "rejections": bt.rejections, "evaluation": ev.to_dict(), "costs_used": {"spread": s.execution.spread, "max_leverage": s.risk.max_leverage}}
            (out / f"{inst}_{name}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
            m = ev.metrics
            print(f"[{inst} {name:7s}] {ev.verdict:5s} | evts={len(events):5d} trades={m['n_trades']:5d} | E={m['expectancy_R']:+.3f}R PF={m['profit_factor']:.2f} worst={m.get('worst_trade_R', 0):.2f} | "
                  f"L {side['long']['n']}/{side['long']['E_R']} S {side['short']['n']}/{side['short']['E_R']} | échecs: {[g.name for g in ev.gates if not g.ok]} | essais={ev.n_trials}", flush=True)


if __name__ == "__main__":
    main()
