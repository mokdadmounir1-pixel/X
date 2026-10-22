"""NEXUS PROP - pipeline M5 reel (5 instruments FTMO). Protocole fige AVANT execution:
 - IS = jusqu'au 2024-12-31 ; TEST FINAL verrouille = 2025-01-01 -> fin, ouvert UNE fois (variant retenu).
 - 13 variantes pre-enregistrees (6 ORB, 1 momentum intraday, 6 TSMOM daily) => N=13 pour le DSR.
 - Retenue = meilleur Sharpe IS. Portes: DSR>=0.95 (IS), PSR(0)>=0.95 et borne basse IC95%>0 (OOS).
 - Taille du risque choisie sur IS uniquement (jamais sur OOS).
"""
import datetime as dt, math, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nexus import stats
from nexus.registry import ExperimentRegistry
from nexus.prop.challenge import two_step
from nexus.prop.intraday import DAY_OFFSET_MIN, daily_series, intraday_momentum_trades, orb_trades
from nexus.prop.mdata import load_m5
from nexus.prop.strategy import StratParams, backtest

U = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/.claude/uploads/1b92574f-1af4-5b52-99dc-b7c5610b5ac0")
FILES = {"US100": "8f137179-FTMO_US100_M5_2022-2026.csv", "US500": "f9e6bb36-FTMO_US500_M5_2022-2026.csv",
         "XAUUSD": "32e7c910-FTMO_XAUUSD_M5_2022-2026.csv", "GBPUSD": "bac71731-FTMO_GBPUSD_M5_2022-2026.csv",
         "GER40": "f694ea5b-FTMO_GER40_M5_2022-2026.csv"}
RISK = 0.0025
SPLIT = int(dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc).timestamp() // 86400)
ann = math.sqrt(252)
OUT = Path(__file__).resolve().parent.parent / "registry_data"; OUT.mkdir(exist_ok=True)
reg = ExperimentRegistry(OUT / "prop_m5.jsonl")

bars = {s: load_m5(U / f, s) for s, f in FILES.items()}
data_ref = ";".join(f"{s}:{b.sha256[:12]}" for s, b in bars.items())
days = sorted({(t - DAY_OFFSET_MIN) // 1440 for b in bars.values() for t in b.ts})
daily_close = {s: {} for s in bars}
for s, b in bars.items():
    for t, c in zip(b.ts, b.c):
        daily_close[s][(t - DAY_OFFSET_MIN) // 1440] = c
common = sorted(set.intersection(*(set(d) for d in daily_close.values())))

variants = {}   # nom -> (ret[], worst[])
def add_trades(name, trades):
    variants[name] = daily_series(trades, days, RISK)
for rm in (15, 30, 60):
    for ex in ("EOD", "2R"):
        add_trades(f"ORB_{rm}_{ex}", [t for b in bars.values() for t in orb_trades(b, rm, ex)])
add_trades("IDM_30_30", [t for s in ("US100", "US500", "GER40") for t in intraday_momentum_trades(bars[s])])
for lb in [(20, 60, 120), (10, 30, 90), (40, 120, 250), (60,), (20,), (120,)]:
    r = backtest({s: [daily_close[s][d] for d in common] for s in bars}, StratParams(lookbacks=lb))
    m = {common[i + 1]: r[i] for i in range(len(r))}
    ret = [m.get(d, 0.0) for d in days]
    variants[f"TSMOM_{'-'.join(map(str, lb))}"] = (ret, [min(x, 0.0) for x in ret])

is_idx = [i for i, d in enumerate(days) if d < SPLIT]
oos_idx = [i for i, d in enumerate(days) if d >= SPLIT]
sl = lambda x, idx: [x[i] for i in idx]
print(f"jours IS={len(is_idx)} OOS={len(oos_idx)}  N variantes={len(variants)}")
srs = {}
for name, (ret, worst) in variants.items():
    r = sl(ret, is_idx); srs[name] = stats.sharpe(r)
    reg.record(hypothesis=name, family="prop-m5", data_ref=data_ref, code_ref="nexus.prop.intraday/strategy",
               params={"risk": RISK}, costs={"spread": "reel", "slip_frac": 0.25}, dates={"is_end": "2024-12-31"},
               status="VERIFIE", outcome=f"IS_SR_ann={srs[name]*ann:.3f}")
    print(f"  {name:18s} IS SR_ann={srs[name]*ann:6.2f}  PnL_total={sum(r)*100:7.1f}%  jours_trade={sum(1 for x in r if x)}")
best = max(srs, key=srs.get)
m = sum(srs.values()) / len(srs); var = sum((x - m) ** 2 for x in srs.values()) / (len(srs) - 1)
n_tr = reg.n_trials("prop-m5")
r_is = sl(variants[best][0], is_idx)
d_is = stats.dsr(r_is, n_tr, var)
print(f"\nRETENU (IS): {best}  SR_ann={srs[best]*ann:.2f}  PSR(0)={stats.psr(srs[best], len(r_is), *stats.moments(r_is)[2:]):.3f}  DSR(N={n_tr})={d_is:.3f}")

ret_o, worst_o = (sl(x, oos_idx) for x in variants[best])        # --- TEST FINAL: ouvert une fois ---
sr_o = stats.sharpe(ret_o)
psr_o = stats.psr(sr_o, len(ret_o), *stats.moments(ret_o)[2:])
lo, hi = stats.stationary_bootstrap_ci(ret_o, lambda x: sum(x) / len(x) / stats.moments(x)[1] * ann, 10, 1000, seed=1)
reg.record(hypothesis="test final verrouille", family="prop-m5-final", data_ref=data_ref, code_ref="idem",
           params={"variant": best}, costs={}, dates={"oos_start": "2025-01-01"}, status="VERIFIE",
           outcome=f"OOS_SR_ann={sr_o*ann:.3f} PSR={psr_o:.3f} CI=[{lo:.2f},{hi:.2f}]")
tot = sum(ret_o)
print(f"TEST FINAL {best}: n={len(ret_o)} jours  SR_ann={sr_o*ann:.2f}  IC95%=[{lo:.2f},{hi:.2f}]  PSR(0)={psr_o:.3f}  PnL={tot*100:.1f}% (a risque {RISK:.2%}/trade)")
srt = sorted(ret_o, reverse=True); pos = sum(x for x in ret_o if x > 0)
print(f"  concentration: top 5% des jours = {sum(srt[:max(1,len(srt)//20)])/pos:.0%} des gains ; pire jour={min(ret_o)*100:.2f}% ; pire intra-jour={min(worst_o)*100:.2f}%")
gates = d_is >= 0.95 and psr_o >= 0.95 and lo > 0
print("PORTES:", "PASSE" if gates else "REJETE -> aucun deploiement justifie par ces donnees")

print("\n-- Choix du multiplicateur de risque sur IS UNIQUEMENT, puis simulation FTMO sur OOS --")
pool_is = list(zip(sl(variants[best][0], is_idx), sl(variants[best][1], is_idx)))
pool_o = list(zip(ret_o, worst_o))
for sc in (1, 2, 3, 4):
    a = two_step(pool_is, sims=1500, seed=5, scale=sc)
    b2 = two_step(pool_o, sims=1500, seed=6, scale=sc)
    print(f"  risque x{sc} ({RISK*sc:.2%}/trade): IS p1={a['phase1']['PASS']:.2f} fail={a['phase1']['FAIL_DAILY']+a['phase1']['FAIL_MAX']:.2f} both={a['pass_both']:.2f}"
          f" | OOS p1={b2['phase1']['PASS']:.2f} fail={b2['phase1']['FAIL_DAILY']+b2['phase1']['FAIL_MAX']:.2f} both={b2['pass_both']:.2f}")
print("registre:", reg.verify(), "essais:", reg.n_trials())
