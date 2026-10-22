"""Sprint 1 - preuves [SYNTHETIQUE] (aucune donnee de marche). Reproductible: seeds fixes.
Les tarifs ci-dessous sont des HYPOTHESES de travail, non verifiees aupres d'un broker."""
import math, random, sys
sys.path.insert(0, ".")
from nexus import stats
from nexus.costs import CostModel, Instrument
from nexus.economics import required_gross_edge_per_trade, ruin_probability_mc

print("== A. DSR sur bruit pur [SYNTHETIQUE] ==")
rng = random.Random(42)
for n_trials in (1, 10, 100, 1000):
    runs = [[rng.gauss(0, 0.01) for _ in range(750)] for _ in range(n_trials)]
    srs = [stats.sharpe(r) for r in runs]
    best = runs[srs.index(max(srs))]
    var = (sum((s - sum(srs)/len(srs))**2 for s in srs)/(len(srs)-1)) if n_trials > 1 else 1/750
    p_naive = stats.psr(max(srs), 750, *stats.moments(best)[2:])
    d = stats.dsr(best, n_trials, var) if n_trials > 1 else p_naive
    print(f"N={n_trials:5d}  meilleur SR annualise={max(srs)*math.sqrt(252):5.2f}  "
          f"PSR(0)={p_naive:.3f}  DSR={d:.3f}")

print("\n== B. Point mort par aller-retour [HYPOTHESE: tarifs a verifier] ==")
mes = Instrument("MES", 0.25, 1.25)
for name, m in {"optimiste": CostModel(0.25, 0.30, 1.0, 0.0),
                "central": CostModel(0.50, 0.35, 1.0, 0.25),
                "pessimiste": CostModel(1.00, 0.40, 2.0, 0.50)}.items():
    print(f"{name:11s} cout A/R={m.round_trip(mes):5.2f} USD  breakeven={m.breakeven_ticks(mes):4.2f} ticks "
          f"| x2 stress={m.round_trip(mes, stress=2):5.2f} USD")

print("\n== C. Edge brut requis/trade, scenario central, 200 USD/mois de couts fixes ==")
c = CostModel(0.50, 0.35, 1.0, 0.25).round_trip(mes)
for tpm in (50, 500, 5000, 50000):
    print(f"{tpm:6d} trades/mois -> edge brut requis {required_gross_edge_per_trade(c, tpm, 200):6.2f} USD/contrat "
          f"({required_gross_edge_per_trade(c, tpm, 200)/mes.tick_value:4.2f} ticks)")

print("\n== D. Probabilite de ruine (equity<=50%) en 1000 trades, p=0.5, R=1.0 (edge nul) [SYNTHETIQUE] ==")
for rf in (0.005, 0.01, 0.02, 0.05):
    print(f"risque/trade={rf:.1%} -> P(ruine)={ruin_probability_mc(0.5, 1.0, rf, 0.5, 1000, 4000, 1):.3f}")
