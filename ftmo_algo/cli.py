"""Interface en ligne de commande : python -m ftmo_algo <commande>."""
from __future__ import annotations
import argparse
import json
import sys
import threading
import time
from pathlib import Path
import numpy as np
import pandas as pd


def _common(p):
    p.add_argument("--instruments", default="US500,EURUSD,XAUUSD")
    p.add_argument("--years", type=float, default=4.0, help="durée des données SYNTHÉTIQUES (si pas de données réelles)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--data-dir", help="dossier de CSV M1/M5 (Dukascopy, export MT5...) nommés INSTRUMENT_xxx.csv")
    p.add_argument("--tz", help="fuseau des CSV si non UTC (ex. Europe/Athens)")
    p.add_argument("--mt5", action="store_true", help="exporter depuis le terminal MT5 local (sur votre machine)")
    p.add_argument("--start", default="2020-01-01"); p.add_argument("--end", default=None)
    p.add_argument("--timeframe", default="M5")
    p.add_argument("--persistence", type=float, default=0.0, help="synthétique : edge planté (tests de puissance)")
    p.add_argument("--out", default="results")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--profile", default="ftmo_2step")
    p.add_argument("--news-csv", help="calendrier économique CSV (time,name)")


def _news(a):
    from .engine.news import NewsCalendar
    return NewsCalendar.from_csv(a.news_csv) if getattr(a, "news_csv", None) else None


def _data(a):
    from .data.loaders import get_universe
    if a.mt5 and not a.end:
        a.end = str(pd.Timestamp.utcnow())[:10]
    dfs = get_universe(a)
    return dfs


def cmd_data_check(a):
    from .data.quality import quality_report
    dfs = _data(a)
    out = [quality_report(d, s) for s, d in dfs.items()]
    synth = any(q["synthetic"] for q in out)
    print(("[SYNTHÉTIQUE] " if synth else "[VÉRIFIÉ] ") + "rapport qualité des données")
    for q in out:
        print(json.dumps(q, ensure_ascii=False))
    short = [q["instrument"] for q in out if q["years"] < 3]
    if short:
        print(f"ATTENTION : < 3 ans de données pour {short} -> verdicts plafonnés à WATCH")
    Path(a.out).mkdir(exist_ok=True)
    (Path(a.out) / "data_quality.json").write_text(json.dumps(out, indent=1))


def cmd_research(a):
    from .research.pipeline import research, to_json, print_table
    dfs = _data(a)
    rep = research(dfs, _news(a), a.workers, a.seed, null_B=a.null, profile=a.profile, out_dir=a.out,
                   tag=a.tag, locked_force=a.force_relock)
    port = rep["_internal"]["portfolio_trades"]
    res = rep["_internal"]["res"]
    Path(a.out).mkdir(exist_ok=True)
    for name, d in res.items():
        oos = d["oos"]
        if len(oos):
            oos[["sym", "entry_t", "exit_t", "r", "grade"]].to_csv(Path(a.out) / f"oos_{name}.csv", index=False)
    if len(port):
        port[["sym", "algo", "entry_t", "exit_t", "r", "grade"]].to_csv(Path(a.out) / "oos_portfolio.csv", index=False)
    to_json(rep, Path(a.out) / "latest.json")
    print_table(rep)
    p = rep["portfolio"]
    print(f"\nPortefeuille : {p.get('verdict')} membres={p.get('members')} {p.get('note','')}")
    print(f"scoring : {rep['scoring']['decision']}")
    print(f"résultats : {a.out}/latest.json  (hash données {rep['data_hash']}, graine {rep['seed']}, v{rep['version']})")


def cmd_calibrate(a):
    from .research.calibrate import calibrate
    real = _data(a) if (a.data_dir or a.mt5) else None
    r = calibrate(tuple(a.instruments.split(",")), a.n, a.years, real, a.null, a.workers, f"{a.out}/calibration.json")
    print(f"{r['label']} séries: {r['kinds']}")
    print(f"taux de faux PASS par série : {r['false_pass_rate_per_series']:.1%} | par test algo : {r['false_pass_rate_per_algo_test']:.1%} "
          f"| faux WATCH par série : {r['false_watch_rate_per_series']:.1%} | espérance OOS moyenne : {r['mean_oos_expectancy_R']} R")
    print("seuil 5 % :", "RESPECTÉ" if r["ok"] else "DÉPASSÉ -> durcir les portes et documenter")


def cmd_target(a):
    from .engine.guardian import PropProfile
    from .target import recommend
    f = Path(a.out) / "latest.json"
    if not f.exists():
        sys.exit("lancer d'abord `research`")
    rep = json.loads(f.read_text())
    prof = PropProfile.load(a.profile)
    synth = rep.get("synthetic")
    print(f"=== CIBLE MENSUELLE {rep['label']} — profil {prof.name} ===")
    if synth:
        print("Données SYNTHÉTIQUES : toute probabilité ci-dessous est NON MESURABLE sur le marché réel (pas de données réelles).")
    for r in (0.25, 0.5, 1.0):
        print(f"  +5 %/mois à {r}% de risque/trade = {5/r:.1f} R nets/mois")
    sets = {k: Path(a.out) / f"oos_{k}.csv" for k in rep["algos"]}
    sets["PORTEFEUILLE"] = Path(a.out) / "oos_portfolio.csv"
    for name, path in sets.items():
        v = rep["portfolio"].get("verdict") if name == "PORTEFEUILLE" else rep["algos"][name]["verdict"]
        if not path.exists():
            continue
        tr = pd.read_csv(path)
        if name != "PORTEFEUILLE" and v != "PASS" and not a.all:
            continue
        flag = "" if v == "PASS" else "  [NON VALIDÉ : verdict " + str(v) + " — indicatif seulement]"
        out = recommend(tr, prof, 5.0, 0.05, a.paths, a.seed)
        print(f"\n--- {name}{flag}")
        if out["status"] != "ok":
            print("  ", out["status"]); continue
        for g in out["grid"]:
            print(f"   risque {g['risk_pct']:4.2f}% : P(mois≥5%)={g['p_month_ge_target']:.1%} médiane={g['median_month_pct']:+.2f}% "
                  f"P(mois<0)={g['p_month_negative']:.1%} P(violation)={g['p_violation']:.1%} "
                  f"P(challenge 1m)={g['p_challenge_1m']:.1%} P(3m)={g['p_challenge_3m']:.1%}")
        if out.get("recommended"):
            b = out["recommended"]
            print(f"   => risque recommandé {b['risk_pct']}% (P(violation)<5 %) ; {out['verdict']}")
        else:
            print("   =>", out["status"])
    if not any(v["verdict"] == "PASS" for v in rep["algos"].values()) and not a.all:
        print("\nAucun algo PASS : aucune probabilité validée. (--all pour un calcul indicatif non validé)")


def _build_runner(a, label_hint=None):
    from .algos.library import BASE_ALGOS
    from .engine.guardian import PropProfile
    from .engine.news import NewsCalendar
    from .engine.sim import SimConfig
    from .live.agent import Agent, SharedData
    from .live.feed import ReplayFeed
    from .live.journal import Journal
    from .live.runner import Runner, KillSwitch
    from .data.quality import quality_report
    dfs = _data(a)
    news = _news(a) or NewsCalendar.default(min(d.index[0] for d in dfs.values()), max(d.index[-1] for d in dfs.values()))
    prof = PropProfile.load(a.profile)
    rep = {}
    f = Path(a.out) / "latest.json"
    if f.exists():
        rep = json.loads(f.read_text())
    syms = list(dfs)
    shared = SharedData(syms, news)
    t_end = max(d.index[-1] for d in dfs.values())
    cut = t_end - pd.Timedelta(days=a.replay_days)
    for s, d in dfs.items():
        shared.preload(s, d[d.index < cut])
    journal = Journal(a.journal)
    fin = rep.get("final_config", {})
    cfg = SimConfig(risk_pct=a.risk, initial_balance=prof.initial_balance)
    agents = [Agent(n, n, fin.get(n), syms, prof, cfg, news, journal, shared) for n in BASE_ALGOS]
    feed = ReplayFeed(dfs, start=cut)
    synth = any(str(d.attrs.get("source", "")).startswith("SYNTH") for d in dfs.values())
    label = "SYNTHÉTIQUE" if synth else "REPLAY"
    pooled = np.concatenate([np.array(v.get("oos_r", []), float) for v in rep.get("algos", {}).values()]) if rep else np.array([])
    band = []
    if len(pooled) >= 20:
        rng = np.random.default_rng(0)
        K = 60
        S = np.cumsum(rng.choice(pooled, size=(1500, K)), axis=1)
        band = [[float(np.percentile(S[:, k], 5)), float(np.percentile(S[:, k], 50)), float(np.percentile(S[:, k], 95))] for k in range(K)]
    tools = {}
    tp = Path(a.out) / "toolbox_status.json"
    if tp.exists():
        tools = json.loads(tp.read_text()).get("tools", {})
    runner = Runner(agents, feed, journal, label, a.speed, news=news, profile=prof, kill=KillSwitch(
        {n: np.array(rep["algos"][n].get("oos_r", []), float) for n in rep.get("algos", {})} if rep else {}),
        data_quality=[quality_report(d, s) for s, d in dfs.items()], tools_status=tools, shared=shared,
        target_info={"risk_pct": a.risk, "target_R": 5.0 / a.risk, "band": band, "streak95": 8} if band else {})
    runner.verdicts = {k: rep.get(k) for k in ("algos", "locked", "label", "data_hash")} if rep else {}
    return runner


def cmd_dashboard(a):
    from .dashboard.server import serve
    runner = _build_runner(a)
    th = threading.Thread(target=runner.run, daemon=True)
    th.start()
    print(f"dashboard : http://127.0.0.1:{a.port}  (badge {runner.label}, {len(runner.feed)} barres M5 à rejouer)")
    serve(runner, a.port)


def cmd_paper(a):
    runner = _build_runner(a)
    n = runner.run(a.max_bars)
    print(f"paper/replay : {n} barres M5, journal {a.journal}")
    for ag in runner.agents:
        tr = ag.trades_df()
        print(f"  {ag.name:18s} trades={len(tr):4d} R={tr.r.sum() if len(tr) else 0:8.2f} statut={ag.status}")


def cmd_demo(a):
    from .live.mt5_bridge import diagnose
    ok, msg = diagnose()
    print(("[DÉMO] " if ok else "[IMPOSSIBLE ICI] ") + msg)
    if not ok:
        sys.exit(2)
    print("Connexion vérifiée. Démarrage de la boucle démo : voir README (section démo).")
    from .live.demo import run_demo
    run_demo(a)


def cmd_install(a):
    from .toolbox.install import install_all
    r = install_all(a.only.split(",") if a.only else None, a.timeout, not a.no_clone)
    print(json.dumps(r.get("summary"), ensure_ascii=False))
    print("statut détaillé : results/toolbox_status.json")


def cmd_bench(a):
    from .toolbox.bench import run_bench
    print(json.dumps(run_bench(), indent=1, ensure_ascii=False))


def cmd_gate(a):
    from .live.gate import real_account_conditions
    print(json.dumps(real_account_conditions(a.verdict, a.locked_exp, a.weeks, a.trades, a.gap), indent=1, ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ftmo_algo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("data-check"); _common(s); s.set_defaults(f=cmd_data_check)
    s = sub.add_parser("research"); _common(s); s.add_argument("--null", type=int, default=99)
    s.add_argument("--tag", default="run"); s.add_argument("--force-relock", action="store_true"); s.set_defaults(f=cmd_research)
    s = sub.add_parser("calibrate"); _common(s); s.add_argument("--n", type=int, default=20); s.add_argument("--null", type=int, default=99)
    s.set_defaults(f=cmd_calibrate)
    s = sub.add_parser("target"); _common(s); s.add_argument("--all", action="store_true"); s.add_argument("--paths", type=int, default=2000)
    s.set_defaults(f=cmd_target)
    for nm, fn in (("dashboard", cmd_dashboard), ("paper", cmd_paper)):
        s = sub.add_parser(nm); _common(s); s.add_argument("--port", type=int, default=8767)
        s.add_argument("--speed", type=float, default=20.0); s.add_argument("--replay-days", type=int, default=20)
        s.add_argument("--risk", type=float, default=0.5); s.add_argument("--journal", default=":memory:")
        s.add_argument("--max-bars", type=int, default=None); s.set_defaults(f=fn)
    s = sub.add_parser("demo"); _common(s); s.add_argument("--risk", type=float, default=0.5); s.add_argument("--minutes", type=int, default=60)
    s.add_argument("--journal", default="results/demo.sqlite"); s.set_defaults(f=cmd_demo)
    s = sub.add_parser("install"); s.add_argument("--only"); s.add_argument("--timeout", type=int, default=600)
    s.add_argument("--no-clone", action="store_true"); s.set_defaults(f=cmd_install)
    s = sub.add_parser("bench"); s.set_defaults(f=cmd_bench)
    s = sub.add_parser("gate"); s.add_argument("--verdict", default="FAIL"); s.add_argument("--locked-exp", type=float, default=None)
    s.add_argument("--weeks", type=float, default=0); s.add_argument("--trades", type=int, default=0)
    s.add_argument("--gap", type=float, default=None); s.set_defaults(f=cmd_gate)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
