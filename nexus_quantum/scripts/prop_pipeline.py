"""Pipeline NEXUS PROP: selection sur IS, test final verrouille ouvert UNE fois, DSR, simulation FTMO.

Usage:
  python scripts/prop_pipeline.py --synthetic null|edge
  python scripts/prop_pipeline.py --csv-dir DIR      # un CSV par symbole (date, close)
"""
import argparse, math, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nexus import stats
from nexus.registry import ExperimentRegistry
from nexus.prop.challenge import two_step
from nexus.prop.data import align, load_close_csv
from nexus.prop.strategy import StratParams, backtest
from nexus.prop.synth import make_prices

GRID = [(20, 60, 120), (10, 30, 90), (40, 120, 250), (60,), (20,), (120,)]
ann = math.sqrt(252)


def run(prices, label, status, data_ref, reg):
    n = len(next(iter(prices.values())))
    cut = int(n * 0.7)
    is_px = {s: p[:cut] for s, p in prices.items()}
    res = {}
    for lb in GRID:                       # TOUS les essais sont enregistres, negatifs inclus
        r = backtest(is_px, StratParams(lookbacks=lb))
        res[lb] = r
        reg.record(hypothesis="TSMOM multi-actifs a cible de vol", family=label, data_ref=data_ref,
                   code_ref="nexus.prop.strategy", params={"lookbacks": lb}, costs={"bps": 1.0},
                   dates={"n_is_days": len(r)}, status=status, outcome=f"IS_SR_ann={stats.sharpe(r)*ann:.3f}")
    srs = {lb: stats.sharpe(r) for lb, r in res.items()}
    best = max(srs, key=srs.get)
    m = sum(srs.values()) / len(srs)
    var = sum((s - m) ** 2 for s in srs.values()) / (len(srs) - 1)
    n_tr = reg.n_trials(label)
    d = stats.dsr(res[best], n_tr, var)
    print(f"[{label}] [{status}] meilleur IS: {best} SR_ann={srs[best]*ann:.2f}  PSR(0)={stats.psr(srs[best], len(res[best]), *stats.moments(res[best])[2:]):.3f}  DSR(N={n_tr})={d:.3f}")
    # test final verrouille: ouvert une seule fois, uniquement pour le variant retenu
    oos = backtest(prices, StratParams(lookbacks=best))[cut:]
    sr_o = stats.sharpe(oos)
    psr_o = stats.psr(sr_o, len(oos), *stats.moments(oos)[2:])
    lo, hi = stats.stationary_bootstrap_ci(oos, lambda x: sum(x) / len(x) / (stats.moments(x)[1]) * ann, 20, 500, seed=1)
    reg.record(hypothesis="test final verrouille", family=label + "-final", data_ref=data_ref, code_ref="nexus.prop.strategy",
               params={"lookbacks": best}, costs={"bps": 1.0}, dates={"n_oos_days": len(oos)}, status=status,
               outcome=f"OOS_SR_ann={sr_o*ann:.3f} PSR={psr_o:.3f}")
    print(f"   TEST FINAL: n={len(oos)} SR_ann={sr_o*ann:.2f} IC95%=[{lo:.2f},{hi:.2f}] PSR(0)={psr_o:.3f}")
    gates = d >= 0.95 and psr_o >= 0.95 and lo > 0
    print(f"   PORTES (DSR>=0.95, PSR_oos>=0.95, IC>0): {'PASSE' if gates else 'REJETE -> pas de deploiement'}")
    sim = two_step(oos, sims=3000, seed=2)
    print(f"   Sim FTMO (bootstrap OOS): P1 pass={sim['phase1']['PASS']:.2f} (daily {sim['phase1']['FAIL_DAILY']:.2f}, max {sim['phase1']['FAIL_MAX']:.2f}, timeout {sim['phase1']['TIMEOUT']:.2f})"
          f" | P2 pass={sim['phase2']['PASS']:.2f} | les deux={sim['pass_both']:.2f}")
    return gates


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", choices=["null", "edge"])
    ap.add_argument("--csv-dir")
    a = ap.parse_args()
    reg = ExperimentRegistry(Path(tempfile.mkdtemp()) / "reg.jsonl")
    if a.synthetic:
        phi = 0.0 if a.synthetic == "null" else 0.08
        px = make_prices(phi=phi, seed=11)
        run(px, f"synthetic-{a.synthetic}", "SYNTHETIQUE", f"make_prices(phi={phi},seed=11)", reg)
    else:
        ser, shas = {}, []
        for f in sorted(Path(a.csv_dir).glob("*.csv")):
            d, p, sha = load_close_csv(f); ser[f.stem] = (d, p); shas.append(f"{f.name}:{sha[:12]}")
        dates, px = align(ser)
        print(f"{len(ser)} symboles, {len(dates)} jours communs {dates[0]}..{dates[-1]}")
        run(px, "real-csv", "VERIFIE", ";".join(shas), reg)   # VERIFIE = provenance des donnees, pas la perf
    print("registre:", reg.verify(), "essais:", reg.n_trials())
