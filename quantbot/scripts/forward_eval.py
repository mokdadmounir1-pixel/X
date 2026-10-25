"""Évaluation des stratégies FIGÉES sur l'échantillon futur collecté par le démon (data/live), selon specs/forward_eval_v1.json.

    python scripts/forward_eval.py specs/forward_eval_v1.json

Tant qu'une stratégie a moins de 60 trades futurs, seul le NOMBRE de trades est affiché (aucune performance). Au seuil, UNE lecture par stratégie,
comptée comme un essai au registre. Aucune période verrouillée, aucun ordre.
"""
import argparse, json, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.lab.forward import evaluate_forward, forward_trades
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


def merged(real_path: Path, live_path: Path) -> pd.DataFrame:
    real = load_mt5_csv(real_path)
    if not live_path.exists():
        return real
    live = load_mt5_csv(live_path)
    allb = pd.concat([real, live[live.index > real.index[-1]]])
    return allb[~allb.index.duplicated(keep="last")].sort_index()


def main():
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--registry", default=str(ROOT / "reports" / "registry.jsonl"))
    args = ap.parse_args()
    fw = json.loads(Path(args.spec).read_text(encoding="utf-8")); base = json.loads((ROOT / fw["base_spec"]).read_text(encoding="utf-8"))
    freeze = pd.Timestamp(json.loads((ROOT / "specs" / "forward_freeze.json").read_text(encoding="utf-8"))["freeze_utc"]).tz_convert("UTC").tz_localize(None)
    reg = TrialRegistry(args.registry); out = ROOT / "reports" / fw["name"]; out.mkdir(parents=True, exist_ok=True)
    for inst, fname in base["instruments"].items():
        df = merged(ROOT / "data" / "real" / fname, ROOT / "data" / "live" / fname)
        measured = costs_from_frame(df)
        for name, scfg in base["strategies"].items():
            if inst not in scfg["instruments"]:
                continue
            key = canonical_hash({"forward": fw["name"], "inst": inst, "strategy": name, "params": scfg["params"], "rule": scfg.get("rule")})
            done = out / f"{inst}_{name}.json"
            if done.exists():
                print(f"[{inst} {name}] déjà lu (une seule lecture) : voir {done.name}"); continue
            s = build_settings(base, inst, measured, df[df.index <= freeze]).with_overrides({"backtest.max_hold_bars": scfg["max_hold_bars"]})
            trades = forward_trades(df, s, EventSignalEngine(s, gen(name, scfg, df)), freeze)
            res = evaluate_forward(trades, fw["min_forward_trades"])
            if not res["disclosed"]:
                print(f"[{inst} {name:7s}] {res['note']}"); continue
            reg.record_trial(key, canonical_hash(str(df.index[-1])), res["expectancy_R"], res["n_forward_trades"], kind="forward_read")
            res.update(instrument=inst, strategy=name, forward_last_bar=str(df.index[-1]), n_trials_after=reg.n_trials())
            done.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
            print(f"[{inst} {name:7s}] {res['verdict']} | trades={res['n_forward_trades']} E={res['expectancy_R']:+.3f}R PF={res['profit_factor']:.2f} p={res['sign_flip_p']:.3f} | essais={reg.n_trials()}")


if __name__ == "__main__":
    main()
