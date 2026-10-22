"""Calibration des portes : toute la recherche sur des séries SANS edge (marches aléatoires indépendantes
et, si fournies, séries réelles mélangées par blocs). Publie le taux de faux PASS."""
from __future__ import annotations
import json
import multiprocessing as mp
from pathlib import Path
import numpy as np
from ..data.synth import make_universe
from .pipeline import research
from .wf import make_surrogate


def _one(args):
    kind, seed, names, years, real, null_B, pers = args
    if kind == "random_walk":
        dfs = make_universe(names, seed=1000 + seed, years=years, persistence=pers)
    else:   # série réelle mélangée : signes de blocs d'un jour inversés -> structure détruite, vol conservée
        dfs = {k: make_surrogate(d, 555 + seed + i) for i, (k, d) in enumerate(real.items())}
    rep = research(dfs, workers=1, seed=seed, null_B=null_B, do_locked=False, verbose=False, registry=False)
    passes = [a for a, r in rep["algos"].items() if r["verdict"] == "PASS"]
    watch = [a for a, r in rep["algos"].items() if r["verdict"] == "WATCH"]
    return {"kind": kind, "seed": seed, "pass": passes, "watch": watch, "scoring_kept": rep["scoring"]["monotone"],
            "exp": {a: r["oos"]["expectancy_R"] for a, r in rep["algos"].items()}}


def calibrate(names=("US500", "EURUSD", "XAUUSD"), n_series=20, years=4.0, real=None, null_B=99, workers=4,
              out="results/calibration.json", seed0=0, persistence=0.0):
    jobs = [("random_walk", seed0 + s, list(names), years, None, null_B, persistence) for s in range(n_series)]
    if real:
        jobs += [("real_shuffled", s, None, None, real, null_B, 0.0) for s in range(max(4, n_series // 5))]
    with mp.get_context("fork").Pool(workers) as pool:
        res = pool.map(_one, jobs, chunksize=1)
    n_algo = 8
    fam = sum(1 for r in res if r["pass"]) / len(res)
    per_test = sum(len(r["pass"]) for r in res) / (len(res) * n_algo)
    rep = {"n_series": len(res), "kinds": {k: sum(1 for r in res if r["kind"] == k) for k in {r["kind"] for r in res}},
           "false_pass_rate_per_series": round(fam, 4), "false_pass_rate_per_algo_test": round(per_test, 4),
           "false_watch_rate_per_series": round(sum(1 for r in res if r["watch"]) / len(res), 4),
           "mean_oos_expectancy_R": round(float(np.mean([v for r in res for v in r["exp"].values()])), 3),
           "threshold": 0.05, "ok": fam <= 0.05, "detail": res, "label": "[SYNTHÉTIQUE]" if not real else "[SYNTHÉTIQUE + réel mélangé]"}
    Path(out).parent.mkdir(exist_ok=True, parents=True)
    Path(out).write_text(json.dumps(rep, indent=1, default=str))
    return rep
