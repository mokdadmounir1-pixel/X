"""Optimisation en MARCHE AVANT d'une stratégie à règles explicites (specs/wf_*.json). Période de RECHERCHE seulement.

Grille, fenêtres et critères sont fixés dans la spec AVANT l'exécution. Le balayage entier compte pour UN essai au registre.
Sortie : reports/<spec>/<instrument>_<stratégie>.json (fenêtres, choix, résultats hors échantillon, repères d'optimisme).
"""
import argparse, itertools, json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.backtest.engine import Backtester
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.lab.locked import split_locked
from quantbot.lab.pipeline import data_hash
from quantbot.lab.registry import TrialRegistry, canonical_hash
from quantbot.lab.specs import build_settings
from quantbot.lab.walkforward import walk_forward
from quantbot.strategies import amd, fvg, orb, vwap
from quantbot.strategies.events import EventSignalEngine


def gen(name, rule, params, df):
    if name == "amd": return amd.events(df, {**amd.PARAMS, **{k: tuple(v) if isinstance(v, list) else v for k, v in params.items()}})
    if name == "vwap": return vwap.events(df, params)
    if name == "orb": return orb.events(df, params)
    return fvg.events(df, rule, params)


def main():
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--registry", default=str(ROOT / "reports" / "registry.jsonl"))
    args = ap.parse_args()
    wf = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    base = json.loads((ROOT / wf["base_spec"]).read_text(encoding="utf-8")); reg = TrialRegistry(args.registry)
    out = ROOT / "reports" / wf["name"]; out.mkdir(parents=True, exist_ok=True)
    for job in wf["jobs"]:
        inst, name = job["instrument"], job["strategy"]; scfg = base["strategies"][name]
        df = load_mt5_csv(ROOT / "data" / "real" / base["instruments"][inst])
        research, _locked = split_locked(df, base["lock_months"], base["lock_min_frac"]); measured = costs_from_frame(df)
        s = build_settings(base, inst, measured, research).with_overrides({"backtest.max_hold_bars": scfg["max_hold_bars"]})
        keys = sorted(job["grid"]); combos = list(itertools.product(*[job["grid"][k] for k in keys]))
        tbc, labels = {}, {}
        for vals in combos:
            params = {**scfg["params"], **dict(zip(keys, vals))}
            label = ",".join(f"{k}={v}" for k, v in zip(keys, vals))
            res = Backtester(s, signal_engine=EventSignalEngine(s, gen(name, scfg.get("rule"), params, research))).run(research)
            tbc[label] = [(t.entry_time, float(t.r_nominal)) for t in res.trades]
            labels[label] = len(res.trades)
        w = job.get("walk", wf["walk"])
        r = walk_forward(tbc, research.index[0], research.index[-1], w["train_days"], w["test_days"], w["min_train_trades"])
        sh = canonical_hash({"wf": wf["name"], "job": job, "walk": w, "base": wf["base_spec"]})
        dh = data_hash(research)
        sr = float(r.oos_r.mean() / r.oos_r.std()) if len(r.oos_r) > 1 and r.oos_r.std() > 0 else 0.0
        counted = reg.record_trial(sh, dh, sr, int(len(r.oos_r)), kind="walk_forward", n_configs=len(combos))
        rep = {"instrument": inst, "strategy": name, "grid": job["grid"], "n_configs": len(combos), "trades_per_config": labels,
               "walk": w, "summary": r.summary, "counted_as_new_trial": counted, "n_trials_total": reg.n_trials(),
               "windows": [{"train_start": str(x.train_start), "test_start": str(x.test_start), "test_end": str(x.test_end), "chosen": x.chosen,
                            "train_E": x.train_expectancy, "train_n": x.train_trades, "oos_n": x.oos_trades, "oos_E": x.oos_expectancy, "note": x.note}
                           for x in r.windows]}
        (out / f"{inst}_{name}.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
        m = r.summary
        f = lambda v, d=3: "—" if v is None else f"{v:+.{d}f}"
        print(f"[{inst} {name:5s}] configs={len(combos):3d} fenêtres tradées={m['n_windows_traded']}/{m['n_windows']} | OOS n={m['n_oos_trades']:4d} "
              f"E={f(m['oos_expectancy_R'])}R PF={f(m['oos_profit_factor'], 2)} fenêtres>0={f(m['oos_positive_window_share'], 2)} | "
              f"entraînement choisi E={f(m['mean_train_expectancy_of_chosen'])}R écart d'optimisme={f(m.get('optimism_gap_R'))}R | "
              f"config moyenne non sélectionnée E={f(m['unselected_average_config_oos_R'])}R | p(sign-flip)={f(m['oos_sign_flip_p'], 3)} | essais={reg.n_trials()}", flush=True)


if __name__ == "__main__":
    main()
