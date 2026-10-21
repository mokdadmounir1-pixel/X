"""Calibration scalp : toute la chaîne sur des marches aléatoires M1 indépendantes -> taux de faux PASS."""
from __future__ import annotations
import json
import multiprocessing as mp
from pathlib import Path
import numpy as np
from ..data.synth import make_universe
from .algos import SCALP_ALGOS
from .pipeline import research


def _one(args):
    seed, names, years, null_B, pers = args
    dfs = make_universe(names, seed=1000 + seed, years=years, persistence=pers, step_min=1)
    rep = research(dfs, workers=1, seed=seed, null_B=null_B, do_locked=False, verbose=False)
    return {"seed": seed, "pass": [a for a, r in rep["algos"].items() if r["verdict"] == "PASS"],
            "watch": [a for a, r in rep["algos"].items() if r["verdict"] == "WATCH"],
            "exp": {a: r["oos"]["expectancy_R"] for a, r in rep["algos"].items()},
            "gross": {a: r["gross_expectancy_R"] for a, r in rep["algos"].items()}}


def calibrate(names=("US500", "EURUSD", "XAUUSD"), n_series=12, years=3.0, null_B=29, workers=4, out="results_scalp/calibration.json",
              seed0=0, persistence=0.0):
    jobs = [(seed0 + s, list(names), years, null_B, persistence) for s in range(n_series)]
    with mp.get_context("fork").Pool(workers) as pool:
        res = pool.map(_one, jobs, chunksize=1)
    n_algo = len(SCALP_ALGOS)
    fam = sum(1 for r in res if r["pass"]) / len(res)
    n = len(res)
    rep = {"n_series": n, "false_pass_rate_per_series": round(fam, 4),
           "false_pass_rate_per_algo_test": round(sum(len(r["pass"]) for r in res) / (n * n_algo), 4),
           "false_watch_rate_per_series": round(sum(1 for r in res if r["watch"]) / n, 4),
           "upper_bound_95_if_zero": round(1 - 0.05 ** (1 / n), 3) if fam == 0 else None,
           "mean_oos_expectancy_R": round(float(np.mean([v for r in res for v in r["exp"].values()])), 3),
           "mean_gross_expectancy_R": round(float(np.mean([v for r in res for v in r["gross"].values()])), 3),
           "threshold": 0.05, "ok": fam <= 0.05, "detail": res, "label": "[SYNTHÉTIQUE]", "persistence": persistence}
    Path(out).parent.mkdir(exist_ok=True, parents=True)
    Path(out).write_text(json.dumps(rep, indent=1, default=str))
    return rep
