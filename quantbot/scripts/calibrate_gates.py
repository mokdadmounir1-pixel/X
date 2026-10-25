"""Calibre les portes sur des marchés SANS edge (le « tell » ne prédit rien) et mesure la puissance sur un edge planté.

Usage : python scripts/calibrate_gates.py [N_nul] [N_puissance]
Le taux de faux PASS est estimé sur des séries indépendantes ; la borne haute (Clopper-Pearson 95 %) est affichée :
« 0 faux PASS sur 60 » ne prouve PAS que le taux est nul (borne ~ 5 %).
"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantbot.config import Settings
from quantbot.lab.gates import GateCfg
from quantbot.lab.locked import split_locked
from quantbot.lab.pipeline import evaluate_research
from quantbot.lab.registry import TrialRegistry
from tests.helpers import OracleSignals, planted_frame


BARS = 5000


def one(args):
    seed, edge, cfg_kw = args
    df = planted_frame(BARS, seed=seed, edge=edge)
    research, _ = split_locked(df)
    ev = evaluate_research(research, Settings(), TrialRegistry(), GateCfg(**cfg_kw), OracleSignals())
    return ev.verdict, [g.name for g in ev.gates if not g.ok]


def upper_bound(k, n, conf=0.95):
    from math import comb
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        cdf = sum(comb(n, i) * mid ** i * (1 - mid) ** (n - i) for i in range(k + 1))
        lo, hi = (mid, hi) if cdf > 1 - conf else (lo, mid)
    return hi


def run(n_null, n_power, cfg_kw):
    with Pool(4) as pool:
        null = pool.map(one, [(1000 + i, False, cfg_kw) for i in range(n_null)])
        power = pool.map(one, [(5000 + i, True, cfg_kw) for i in range(n_power)])
    fp = sum(v == "PASS" for v, _ in null)
    return {"cfg": cfg_kw, "null_n": n_null, "false_pass": fp, "false_pass_rate": fp / n_null,
            "false_pass_upper95": round(upper_bound(fp, n_null), 3),
            "false_watch": sum(v == "WATCH" for v, _ in null),
            "power_n": n_power, "power_pass": sum(v == "PASS" for v, _ in power),
            "power_verdicts": {v: sum(x == v for x, _ in power) for v in ("PASS", "WATCH", "FAIL")}}


if __name__ == "__main__":
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    n_null = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    n_pow = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    kw = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    print(json.dumps(run(n_null, n_pow, kw), indent=1))
