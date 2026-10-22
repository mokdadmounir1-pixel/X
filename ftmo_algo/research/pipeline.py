"""Orchestration de la recherche : walk-forward + portes + test nul + période verrouillée."""
from __future__ import annotations
import json
import time
from dataclasses import replace
from pathlib import Path
import numpy as np
import pandas as pd
from ..algos.library import ALGOS, BASE_ALGOS, EXIT_VARIANTS
from ..data.loaders import data_hash
from ..data.quality import quality_report
from ..engine.guardian import PropProfile
from ..engine.sim import Sim, SimConfig
from . import stats as st
from .stats import reality_check
from .gates import GateCfg, GATE_CLASS, cheap_gates, null_gate, verdict
from .ml import ml_filter
from .split import split_locked, final_evaluation
from .wf import (shift_signals, make_surrogate_stationary, build_ctxs, run_variants, make_folds, walk_forward, modal_variant, in_windows, parse_vkey,
                 vkey, null_distribution, sim_trades, KEEP, cands_default, portfolio_sim)
from .. import __version__
from ..registry import TrialRegistry, family_key, experiment_id


def _summ(r):
    r = np.asarray(r, float)
    return {"n": int(len(r)), "expectancy_R": round(st.expectancy(r), 3), "pf": round(min(st.profit_factor(r), 99), 2),
            "win_rate": round(float((r > 0).mean()), 3) if len(r) else 0.0, "total_R": round(float(r.sum()), 1)}


def _years(dfs):
    t0 = min(d.index[0] for d in dfs.values()); t1 = max(d.index[-1] for d in dfs.values())
    return (t1 - t0).days / 365.25


def research(dfs: dict, news=None, workers=1, seed=0, cfg: GateCfg | None = None, null_B=99, profile="ftmo_2step",
             do_locked=True, out_dir="results", tag="run", algos=None, verbose=True, locked_force=False,
             lock_months=12, registry=True) -> dict:
    cfg = cfg or GateCfg()
    prof = PropProfile.load(profile)
    t_start = time.time()
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    algos = algos or BASE_ALGOS
    src = {d.attrs.get("source", "?") for d in dfs.values()}
    synthetic = any(str(s).startswith(("SYNTH", "SURROG")) for s in src)
    reg = TrialRegistry(Path(out_dir) / "trials_registry.jsonl")
    fam = family_key(dfs, not synthetic)
    eid = experiment_id("research", fam, data_hash(dfs), algos, json.dumps(cfg.__dict__, sort_keys=True))
    prior = reg.prior_trials(fam, exclude_experiment=eid) if registry else 0
    years = _years(dfs)
    rdata, locked = split_locked(dfs, lock_months)
    folds_t0 = max(d.index[0] for d in rdata.dfs.values())
    folds = make_folds(folds_t0, rdata.lock_start)
    rep = {"version": __version__, "data_hash": data_hash(dfs), "seed": seed, "source": sorted(src), "synthetic": synthetic,
           "years": round(years, 2), "instruments": sorted(dfs), "lock_start": str(rdata.lock_start),
           "folds": [{"test_start": str(pd.Timestamp(f.test_start, tz="UTC")), "test_end": str(pd.Timestamp(f.test_end, tz="UTC"))} for f in folds],
           "profile": prof.name, "gate_cfg": cfg.__dict__, "quality": [quality_report(d, s) for s, d in dfs.items()],
           "label": "[SYNTHÉTIQUE]" if synthetic else "[VÉRIFIÉ sur données réelles]"}
    log(f"[research] données: {sorted(src)} {years:.1f} ans, verrou dès {rdata.lock_start:%Y-%m-%d}, {len(folds)} plis")
    ctxs = build_ctxs(rdata.dfs, news)
    t = time.time()
    tv = run_variants(ctxs, algos, workers=workers)
    nvar = {a: len(tv[a]) for a in algos}
    log(f"[research] {sum(nvar.values())} variantes×instruments simulées en {time.time()-t:.0f}s")
    # ---- scoring : A+ > A > B prouvé hors échantillon ?
    by_grade = {0: [], 1: [], 2: []}
    wf_all = {}
    for a in algos:
        oos, chosen = walk_forward(tv[a], folds, grade_min=0)
        wf_all[a] = (oos, chosen)
        for g in by_grade:
            if len(oos):
                by_grade[g].append(oos.r.to_numpy()[oos.grade.to_numpy() == g])
    gr = {g: (np.concatenate(v) if v else np.array([])) for g, v in by_grade.items()}
    ge = {g: st.expectancy(gr[g]) for g in gr}
    mono = all(len(gr[g]) >= 30 for g in gr) and ge[2] > ge[1] > ge[0]
    rep["scoring"] = {"A+": _summ(gr[2]), "A": _summ(gr[1]), "B": _summ(gr[0]), "monotone": bool(mono),
                      "decision": "scoring conservé : seuls A+ et A tradés" if mono else
                      "scoring SUPPRIMÉ (A+ > A > B non prouvé hors échantillon) : tous les grades sont tradés"}
    grade_min = 1 if mono else 0
    log(f"[research] scoring A+={ge[2]:.3f} A={ge[1]:.3f} B={ge[0]:.3f} -> {rep['scoring']['decision']}")
    # ---- étude des sorties : espérance OOS moyenne par type de sortie (sans sélection => non biaisée)
    ex_stat = {}
    for a in algos:
        for k, df in tv[a].items():
            if len(df) == 0:
                continue
            e = k.split("@")[1]
            m = in_windows(df.entry_t.to_numpy(), folds)
            ex_stat.setdefault(e, []).append(df.r.to_numpy()[m])
    rep["exit_study"] = {e: _summ(np.concatenate(v)) for e, v in ex_stat.items()}
    rep["exit_study"]["_note"] = ("moyenne sur toutes les variantes de paramètres, fenêtres OOS uniquement ; "
                                  "fixed3_wkflat = fermeture forcée avant le week-end vs fixed3 = conservation")
    # ---- walk-forward final par algo
    res, n_tests = {}, len(algos) + 1
    for a in algos:
        oos, chosen = walk_forward(tv[a], folds, grade_min=grade_min)
        res[a] = {"oos": oos, "chosen": chosen}
    # ---- ML
    cands = cands_default(ctxs, [x for x in algos if x != "regime_router"], workers)
    ml_oos, ml_base, ml_info = ml_filter(cands, folds, [x for x in algos if x != "regime_router"])
    if len(ml_oos):
        ml_oos = ml_oos[ml_oos.grade >= grade_min]
    res["ml_filter"] = {"oos": ml_oos, "chosen": ml_info, "baseline": ml_base}
    # ---- portes
    names = algos + ["ml_filter"]
    dsr_srs = {a: [st.sharpe_stats(df.r.to_numpy())[0] for df in tv[a].values() if len(df) > 10] for a in algos}
    tpy_den = max(0.5, (rdata.lock_start - folds_t0).days / 365.25)
    for a in names:
        oos = res[a]["oos"]
        r = oos.r.to_numpy() if len(oos) else np.array([])
        row = {"oos": _summ(r), "scoring_grade_min": grade_min}
        # coûts x2 : on rejoue les variantes choisies
        if a != "ml_filter":
            ch = {c["variant"] for c in res[a]["chosen"] if c["variant"]}
            c2 = run_variants(ctxs, [a], cost_mult=2.0, only={a: ch}, workers=1)[a] if ch else {}
            parts = []
            for c in res[a]["chosen"]:
                if c["variant"] and c["variant"] in c2:
                    df = c2[c["variant"]]
                    m = (df.entry_t.to_numpy() >= c["test_start"]) & (df.entry_t.to_numpy() < c["test_end"]) & (df.grade.to_numpy() >= grade_min)
                    parts.append(df[m].r.to_numpy())
            r2 = np.concatenate(parts) if parts else np.array([])
            mv = modal_variant(res[a]["chosen"])
            nb = []
            if mv:
                p0, e0 = parse_vkey(mv)
                for np_ in ALGOS[a].neighbors(p0) if ALGOS[a].grid else []:
                    df = tv[a].get(vkey(np_, e0))
                    if df is not None and len(df):
                        m = in_windows(df.entry_t.to_numpy(), folds) & (df.grade.to_numpy() >= grade_min)
                        nb.append(st.expectancy(df.r.to_numpy()[m]))
            row["modal_variant"] = mv
        else:
            ch = []
            base = res[a]["baseline"]
            r2 = np.array([])
            row["baseline_unfiltered"] = _summ(base.r.to_numpy() if len(base) else [])
            nb = None
            row["ml_folds"] = ml_info
            # coût x2 du filtre ML : même sélection, coûts doublés
            if len(ml_oos):
                only = {x: {vkey(ALGOS[x].default, "fixed3")} for x in cands.algo.unique()}
                c2 = run_variants(ctxs, list(only), cost_mult=2.0, only=only, workers=1)
                keep = []
                for x in only:
                    df = c2[x][vkey(ALGOS[x].default, "fixed3")]
                    if len(df):
                        key = set(zip(ml_oos[ml_oos.algo == x].sym, ml_oos[ml_oos.algo == x].entry_t))
                        keep.append(df[[(s, t_) in key for s, t_ in zip(df.sym, df.entry_t)]].r.to_numpy())
                r2 = np.concatenate(keep) if keep else np.array([])
        tpy = len(r) / tpy_den if len(r) else 0
        if a == "ml_filter":
            g = cheap_gates(r, r2, [1.0], cfg, prof.max_loss_pct, tpy)
            g["g8_plateau"] = (True, "n/a (pas de paramètres libres : seuil fixé a priori)", cfg.plateau_frac)
        else:
            g = cheap_gates(r, r2, nb, cfg, prof.max_loss_pct, tpy)
        trial_n = max(2, nvar.get(a, 40) * len(dfs) if a != "ml_filter" else 2 * len(algos)) + prior
        srs = dsr_srs.get(a, [0.0, 0.1])
        dsr_p = st.deflated_sharpe(r, srs, trial_n) if len(r) > 10 else 0.0
        row["oos_r"] = [round(float(x), 3) for x in r[:3000]]
        row.update(gates={k: {"pass": bool(v[0]), "value": v[1], "threshold": v[2]} for k, v in g.items()},
                   dsr=round(dsr_p, 3), n_trials=trial_n)
        res[a]["row"] = row; res[a]["gates"] = g; res[a]["r"] = r
    # ---- test nul pour les candidats qui passent les portes peu coûteuses
    elig = [a for a in names if all(v[0] for v in res[a]["gates"].values())
            and res[a]["row"]["dsr"] >= cfg.dsr_min]
    if elig:
        jobs = []
        for a in elig:
            if a == "ml_filter":
                jobs.append((a, [x for x in algos if x != "regime_router"], None, folds))
                continue
            p0, e0 = parse_vkey(res[a]["row"]["modal_variant"])
            jobs.append((a, p0, e0, folds))
        log(f"[research] test nul ({null_B} surrogates) pour {elig}")
        nd = null_distribution(rdata.dfs, jobs, null_B, workers, news)
        base_jobs = [j for j in jobs if j[0] != "ml_filter"]
        nd2 = null_distribution(rdata.dfs, base_jobs, null_B, workers, news, kind="stationary") if base_jobs else {}
        for a in elig:
            obs = res[a]["row"]["oos"]["expectancy_R"]
            battery = {"signe_aleatoire_par_jour": null_gate(obs, nd[a][:, 0], n_tests, cfg)}
            if a in nd2:
                battery["bootstrap_stationnaire_4h"] = null_gate(obs, nd2[a][:, 0], n_tests, cfg)
                p0, e0 = parse_vkey(res[a]["row"]["modal_variant"])
                battery["decalage_des_signaux"] = _shift_gate(ctxs, a, p0, e0, folds, grade_min, obs, n_tests, cfg, workers)
            ok = all(v[0] for v in battery.values())
            res[a]["gates"]["g4_null"] = (ok, {k: v[1] for k, v in battery.items()}, {k: v[2] for k, v in battery.items()})
            res[a]["row"]["null"] = {"obs": obs, "null_mean": round(float(nd[a][:, 0].mean()), 3),
                                     "null_p95": round(float(np.percentile(nd[a][:, 0], 95)), 3),
                                     "batterie": {k: {"ok": bool(v[0]), "p": v[1], "alpha": v[2]} for k, v in battery.items()}}
            res[a]["null_pairs"] = nd[a]
    for a in names:
        g = res[a]["gates"]; row = res[a]["row"]
        if "g4_null" not in g:
            g["g4_null"] = (False, "non évalué (porte précédente échouée)", cfg.null_alpha)
        row["gates"] = {k: {"pass": bool(v[0]), "value": v[1], "threshold": v[2], "classe": GATE_CLASS.get(k, "")} for k, v in g.items()}
        exp = row["oos"]["expectancy_R"]
        v, why = verdict(g, row["dsr"], years, cfg, exp)
        row["verdict"], row["reason"] = v, why
        row["target_math"] = target_math(exp, row["oos"]["n"], tpy_den, prof)
    rep["algos"] = {a: res[a]["row"] for a in names}
    cols, mat = _daily_matrix({a: res[a]["oos"] for a in algos})
    rc = reality_check(mat, seed=seed) if len(cols) else {"p": None}
    rc["strategies"] = cols
    rc["note"] = ("White Reality Check sur les rendements quotidiens OOS des algos de base (bootstrap stationnaire, blocs ~5 j) : "
                  "p élevé = le meilleur algo n'est pas distinguable d'un choix de hasard parmi ceux testés.")
    rep["reality_check"] = rc
    for a in algos:
        mv = rep["algos"][a].get("modal_variant")
        if mv:
            rep["algos"][a]["intrabar"] = _intrabar(ctxs, a, mv, folds, grade_min)
    rep["hypotheses"] = {a: {"hypothese": ALGOS[a].hypothesis, "invalidation": ALGOS[a].invalidation} for a in names}
    # ---- portefeuille (gardien, plafonds de groupe) + portes au niveau portefeuille
    members = [a for a in algos if rep["algos"][a]["verdict"] == "PASS"]
    port_trades = pd.DataFrame()
    if not members:
        rep["portfolio"] = {"members": [], "verdict": "AUCUN", "note": "aucun algo PASS : pas de portefeuille validé"}
    else:
        chosen = {a: res[a]["chosen"] for a in members}
        pres = portfolio_sim(ctxs, chosen, members, cfg.risk_pct, 1.0, grade_min, prof)
        port_trades = pres.trades
        r = port_trades.r.to_numpy() if len(port_trades) else np.array([])
        r2 = portfolio_sim(ctxs, chosen, members, cfg.risk_pct, 2.0, grade_min, prof).trades
        r2 = r2.r.to_numpy() if len(r2) else np.array([])
        g = cheap_gates(r, r2, [1.0], cfg, prof.max_loss_pct, len(r) / tpy_den if len(r) else 0)
        g["g8_plateau"] = (True, "membres : plateau validé individuellement", cfg.plateau_frac)
        if all(v[0] for v in g.values()):
            pj = [("pf:" + a, None, None, None) for a in members]
            jobs_p = [(a, *parse_vkey(res[a]["row"]["modal_variant"]), folds) for a in members]
            ndp = {a: res[a]["null_pairs"] for a in members if "null_pairs" in res[a]}
            if len(ndp) == len(members):
                num = sum(ndp[a][:, 0] * ndp[a][:, 1] for a in members); den = sum(ndp[a][:, 1] for a in members)
                nullp = num / np.maximum(den, 1)
                g["g4_null"] = null_gate(st.expectancy(r), nullp, n_tests, cfg)
        g.setdefault("g4_null", (False, "non évalué", cfg.null_alpha))
        dsr_p = st.deflated_sharpe(r, [x for a in members for x in dsr_srs[a]], sum(rep["algos"][a]["n_trials"] for a in members)) if len(r) > 10 else 0.0
        v, why = verdict(g, dsr_p, years, cfg, st.expectancy(r))
        rep["portfolio"] = {"members": members, "verdict": v, "reason": why, "oos": _summ(r), "dsr": round(dsr_p, 3),
                            "gates": {k: {"pass": bool(x[0]), "value": x[1], "threshold": x[2]} for k, x in g.items()},
                            "guardian_breach": pres.breach, "rejected": pres.rejected}
    # ---- période verrouillée : configuration gelée, évaluée UNE fois, publiée telle quelle
    final_cfg = {a: res[a]["row"].get("modal_variant") for a in algos}
    rep["final_config"] = final_cfg
    if do_locked:
        def _ev(full, lock_start):
            ctx_full = build_ctxs(full, news)
            out = {}
            for a in algos:
                mv = final_cfg.get(a)
                if not mv:
                    out[a] = {"n": 0, "note": "aucune variante sélectionnée"}; continue
                p0, e0 = parse_vkey(mv)
                parts = []
                for s, c in ctx_full.items():
                    tr = sim_trades(c, ALGOS[a].generate(c, p0, EXIT_VARIANTS[e0]))
                    tr = tr[(tr.entry_t >= lock_start.value) & (tr.grade >= grade_min)]
                    parts.append(tr.r.to_numpy())
                r = np.concatenate(parts)
                out[a] = {**_summ(r), "variant": mv, "verdict_research": rep["algos"][a]["verdict"]}
            return out
        rep["locked"] = final_evaluation(locked, _ev, out_dir, tag, force=locked_force)
        rep["locked"]["_note"] = ("Résultat publié tel quel : configuration gelée avant lecture, évaluée une seule fois. "
                                  "ML non évalué sur le verrou (modèle gelé non persisté dans cette version).")
    if registry:
      reg.log("research", fam, sum(nvar.values()) * len(dfs), data_hash(dfs), algos, {"cfg": cfg.__dict__, "seed": seed, "null_B": null_B},
            {a: rep["algos"][a]["verdict"] for a in names}, f"tag={tag}")
    rep["trials_registry"] = {"famille": fam, "essais_anterieurs_comptes_dans_le_DSR": prior,
                              "chaine": reg.verify()[1] if registry else "désactivé", "fichier": str(reg.path)}
    rep["runtime_s"] = round(time.time() - t_start, 1)
    rep["_internal"] = {"portfolio_trades": port_trades, "res": res, "tv": tv, "ctxs": ctxs, "folds": folds, "grade_min": grade_min}
    return rep


_SH = {}


def _shift_job(k):
    ctxs, algo, params, ex, folds, gmin = _SH["a"]
    rs = []
    for sym, ctx in ctxs.items():
        sig = shift_signals(ALGOS[algo].generate(ctx, params, EXIT_VARIANTS[ex]), ctx.mk.c, k)
        tr = sim_trades(ctx, sig)
        if len(tr):
            m = in_windows(tr.entry_t.to_numpy(), folds) & (tr.grade.to_numpy() >= gmin)
            rs.append(tr.r.to_numpy()[m])
    r = np.concatenate(rs) if rs else np.array([])
    return float(r.mean()) if len(r) else 0.0


def _shift_gate(ctxs, algo, params, ex, folds, gmin, obs, n_tests, cfg, workers, first_day=7, days=50, bars_per_day=96):
    """Si la valeur vient du timing précis des signaux, les mêmes signaux décalés de ±7..56 jours (distances relatives
    conservées) doivent faire nettement moins bien. H0 : le moment exact n'a aucune importance. Décalages ≥ 7 jours
    (fixé a priori) : en deçà, une tendance persistante recouvre encore le signal décalé et le test n'est plus un test nul."""
    import multiprocessing as mp
    _SH["a"] = (ctxs, algo, params, ex, folds, gmin)
    ks = [d * bars_per_day * sgn for d in range(first_day, first_day + days) for sgn in (-1, 1)]
    if workers > 1:
        with mp.get_context("fork").Pool(workers) as pool:
            sh = np.array(pool.map(_shift_job, ks, chunksize=4))
    else:
        sh = np.array([_shift_job(k) for k in ks])
    return null_gate(obs, sh, n_tests, cfg)


def _daily_matrix(oos_by_algo: dict):
    ser = {}
    for a, oos in oos_by_algo.items():
        if len(oos) < 10:
            continue
        day = (oos.exit_t.to_numpy("int64") // 86_400_000_000_000)
        ser[a] = pd.Series(oos.r.to_numpy(), index=day).groupby(level=0).sum()
    if not ser:
        return [], np.zeros((0, 0))
    df = pd.DataFrame(ser)
    full = np.arange(int(df.index.min()), int(df.index.max()) + 1)
    df = df.reindex(full).fillna(0.0)
    return list(df.columns), df.to_numpy()


def _intrabar(ctxs, algo, variant, folds, grade_min):
    """Fourchette d'incertitude due à l'OHLC : mêmes signaux, stop-d'abord (pessimiste) contre cible-d'abord (optimiste)
    quand l'ordre stop/cible dans une barre est inconnu même après résolution M5."""
    p0, e0 = parse_vkey(variant)
    out, amb = {}, []
    for pol in ("stop", "target"):
        rs = []
        for sym, ctx in ctxs.items():
            tr = sim_trades(ctx, ALGOS[algo].generate(ctx, p0, EXIT_VARIANTS[e0]), ambiguity=pol)
            if len(tr):
                m = in_windows(tr.entry_t.to_numpy(), folds) & (tr.grade.to_numpy() >= grade_min)
                rs.append(tr.r.to_numpy()[m])
                if pol == "stop":
                    amb.append(tr.amb.to_numpy()[m])
        out[pol + "_d_abord"] = _summ(np.concatenate(rs) if rs else [])
    a = np.concatenate(amb) if amb else np.array([])
    out["part_trades_ambigus"] = round(float(a.mean()), 3) if len(a) else 0.0
    out["ecart_E_R"] = round(out["target_d_abord"]["expectancy_R"] - out["stop_d_abord"]["expectancy_R"], 3)
    return out


def target_math(exp_r, n_oos, years_oos, prof, risks=(0.25, 0.5, 0.75, 1.0)):
    """Traduction obligatoire de la cible +5 %/mois en unités de risque (jamais un objectif d'optimisation)."""
    out = {f"risk_{r}%": {"R_par_mois_requis": round(5.0 / r, 2)} for r in risks}
    tpm = n_oos / (years_oos * 12) if years_oos else 0
    out["trades_par_mois_observes"] = round(tpm, 2)
    out["R_par_mois_observes"] = round(exp_r * tpm, 2)
    out["pct_mois_a_0.5%"] = round(exp_r * tpm * 0.5, 2)
    return out


def to_json(rep, path):
    rep = {k: v for k, v in rep.items() if k != "_internal"}
    Path(path).parent.mkdir(exist_ok=True, parents=True)
    Path(path).write_text(json.dumps(rep, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def print_table(rep):
    print(f"\n=== VERDICTS {rep['label']}  données {rep['years']} ans | hash {rep['data_hash']} | v{rep['version']} ===")
    print(f"{'algo':18s} {'verdict':7s} {'n':>5s} {'exp(R)':>7s} {'PF':>5s} {'DSR':>5s}  portes échouées / raison")
    for a, r in rep["algos"].items():
        o = r["oos"]
        print(f"{a:18s} {r['verdict']:7s} {o['n']:5d} {o['expectancy_R']:7.3f} {o['pf']:5.2f} {r['dsr']:5.2f}  {r['reason']}")
    if "locked" in rep:
        print("\n--- PÉRIODE VERROUILLÉE (évaluée une seule fois, publiée telle quelle) ---")
        for a, r in rep["locked"].items():
            if a.startswith("_"):
                continue
            print(f"{a:18s} n={r.get('n')} exp={r.get('expectancy_R')} pf={r.get('pf')} total_R={r.get('total_R')}")
