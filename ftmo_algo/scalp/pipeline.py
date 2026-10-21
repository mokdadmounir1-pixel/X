"""Recherche scalp M1 : walk-forward + période verrouillée + portes + test nul + DSR, avec les outils du dépôt.
Différences assumées avec `research` (M15) : barres M1, sorties courtes (time-stop en minutes), RR net minimal 1,3 (le scalp ne vit
pas à RR 2,5), risque 0,15 %/trade, seuils de portes propres au scalp (nombreux trades, petite espérance nette), deux tests de stress
supplémentaires : coûts ×1,5 et retard d'exécution d'une barre."""
from __future__ import annotations
import multiprocessing as mp
import time
from dataclasses import replace
import numpy as np
import pandas as pd
from ..engine.guardian import PropProfile
from ..engine.sim import Sim, SimConfig
from ..data.loaders import data_hash
from ..data.quality import quality_report
from ..research import stats as st
from ..research.gates import GateCfg, cheap_gates, null_gate, verdict
from ..research.pipeline import _summ, target_math
from ..research.split import split_locked, final_evaluation
from ..research.wf import (KEEP, make_folds, walk_forward, modal_variant, in_windows, parse_vkey, vkey, make_surrogate)
from .. import __version__
from .algos import SCALP_ALGOS, SCALP_EXITS, delay_signals
from .costs import cost_report
from .ctx import ScalpCtx

MIN_RR_NET = 1.3
SCALP_GATES = GateCfg(min_trades=300, min_exp=0.08, min_pf=1.12, null_alpha=0.10, risk_pct=0.15, dd_frac=0.60,
                      mc_paths=2000, min_years=3.0, dsr_min=0.5)
COST_STRESS = 1.5
_G: dict = {}


def sim_scalp(ctx: ScalpCtx, sig, cost_mult=1.0, delay=0, risk_pct=0.15) -> pd.DataFrame:
    if delay:
        sig = delay_signals(sig, delay)
    cfg = SimConfig(risk_pct=risk_pct, cost_mult=cost_mult, use_guardian=False, grades=(2, 1, 0), min_rr_net=MIN_RR_NET)
    tr = Sim({ctx.sym: ctx.mk}, cfg, PropProfile()).run([sig]).trades
    if len(tr) == 0:
        return pd.DataFrame(columns=KEEP)
    return tr[KEEP]


def build_ctxs(dfs: dict, news=None) -> dict:
    return {s: ScalpCtx(s, d, news=news) for s, d in dfs.items()}


def _task(a):
    algo, sym, cost_mult, delay, only = a
    ctx = _G["ctxs"][sym]
    alg = SCALP_ALGOS[algo]
    out = {}
    for p in alg.combos():
        todo = [e for e in SCALP_EXITS if only is None or vkey(p, e) in only]
        if not todo:
            continue
        sig0 = alg.generate(ctx, p, SCALP_EXITS[todo[0]])
        for e in todo:
            out[vkey(p, e)] = sim_scalp(ctx, replace(sig0, exit=SCALP_EXITS[e]), cost_mult, delay)
    return algo, sym, out


def run_variants(ctxs, algos, cost_mult=1.0, delay=0, only=None, workers=1) -> dict:
    _G["ctxs"] = ctxs
    tasks = [(a, s, cost_mult, delay, only.get(a) if isinstance(only, dict) else only) for a in algos for s in ctxs]
    if workers > 1:
        with mp.get_context("fork").Pool(workers) as pool:
            res = pool.map(_task, tasks, chunksize=1)
    else:
        res = [_task(t) for t in tasks]
    agg: dict = {a: {} for a in algos}
    for algo, sym, out in res:
        for k, df in out.items():
            agg[algo].setdefault(k, []).append(df)
    return {a: {k: pd.concat(v, ignore_index=True) if any(len(x) for x in v) else v[0] for k, v in d.items()}
            for a, d in agg.items()}


def _null_job(args):
    b, dfs, jobs, news = args
    ctxs = build_ctxs({s: make_surrogate(d, 7919 * b + i, block_bars=1) for i, (s, d) in enumerate(dfs.items())}, news)
    res = {}
    for (algo, params, ex, wins) in jobs:
        rs = []
        for ctx in ctxs.values():
            tr = sim_scalp(ctx, SCALP_ALGOS[algo].generate(ctx, params, SCALP_EXITS[ex]))
            if len(tr):
                rs.append(tr.r.to_numpy()[in_windows(tr.entry_t.to_numpy(), wins)])
        r = np.concatenate(rs) if rs else np.array([])
        res[algo] = (float(r.mean()) if len(r) else 0.0, len(r))
    return res


def null_distribution(dfs, jobs, B, workers, news):
    args = [(b, dfs, jobs, news) for b in range(B)]
    if workers > 1:
        with mp.get_context("fork").Pool(workers) as pool:
            out = pool.map(_null_job, args, chunksize=1)
    else:
        out = [_null_job(a) for a in args]
    return {j[0]: np.array([o[j[0]] for o in out]) for j in jobs}


def compliance(oos: pd.DataFrame, years: float, bar_min=1) -> dict:
    """Indicateurs FTMO/anti-HFT à contrôler [HYPOTHÈSE sur les seuils : sources tierces, voir SCALP.md]."""
    if not len(oos):
        return {}
    days = max(1.0, years * 252)
    dur = oos.bars.to_numpy() * bar_min
    return {"trades_par_jour": round(len(oos) / days, 2), "duree_mediane_min": float(np.median(dur)),
            "part_trades_<=1_barre": round(float((oos.bars.to_numpy() <= 1).mean()), 3),
            "requetes_serveur_estimees_par_jour": round(len(oos) / days * 4, 1),
            "note": "≈4 requêtes/trade (ordre, SL/TP, modification, clôture) ; seuil évoqué par des sources tierces : 2000/jour"}


def research(dfs: dict, news=None, workers=1, seed=0, null_B=49, out_dir="results_scalp", tag="run", algos=None,
             cfg: GateCfg | None = None, lock_months=12, do_locked=True, locked_force=False, verbose=True) -> dict:
    cfg = cfg or SCALP_GATES
    prof = PropProfile.load("ftmo_2step")
    t_start = time.time()
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    algos = algos or list(SCALP_ALGOS)
    src = {d.attrs.get("source", "?") for d in dfs.values()}
    synthetic = any(str(s).startswith(("SYNTH", "SURROG")) for s in src)
    years = (max(d.index[-1] for d in dfs.values()) - min(d.index[0] for d in dfs.values())).days / 365.25
    rdata, locked = split_locked(dfs, lock_months)
    t0 = max(d.index[0] for d in rdata.dfs.values())
    folds = make_folds(t0, rdata.lock_start)
    rep = {"version": __version__, "mode": "scalp_M1", "data_hash": data_hash(dfs), "seed": seed, "source": sorted(src),
           "synthetic": synthetic, "years": round(years, 2), "instruments": sorted(dfs), "lock_start": str(rdata.lock_start),
           "n_folds": len(folds), "gate_cfg": cfg.__dict__, "min_rr_net": MIN_RR_NET, "cost_stress": COST_STRESS,
           "quality": [quality_report(d, s) for s, d in dfs.items()],
           "label": "[SYNTHÉTIQUE]" if synthetic else "[VÉRIFIÉ sur données réelles]"}
    rep["cost_feasibility"] = cost_report(rdata.dfs)
    log(f"[scalp] {sorted(src)} {years:.1f} ans, verrou dès {rdata.lock_start:%Y-%m-%d}, {len(folds)} plis")
    ctxs = build_ctxs(rdata.dfs, news)
    t = time.time()
    tv = run_variants(ctxs, algos, workers=workers)
    nvar = {a: len(tv[a]) for a in algos}
    log(f"[scalp] {sum(nvar.values())} variantes×instruments en {time.time()-t:.0f}s")
    # étude des sorties : espérance OOS moyenne par sortie (sans sélection)
    ex_stat = {}
    for a in algos:
        for k, df in tv[a].items():
            if len(df):
                ex_stat.setdefault(k.split("@")[1], []).append(df.r.to_numpy()[in_windows(df.entry_t.to_numpy(), folds)])
    rep["exit_study"] = {e: _summ(np.concatenate(v)) for e, v in ex_stat.items()}
    res = {}
    n_tests = len(algos)
    for a in algos:
        oos, chosen = walk_forward(tv[a], folds, min_n=60)
        res[a] = {"oos": oos, "chosen": chosen}
    dsr_srs = {a: [st.sharpe_stats(df.r.to_numpy())[0] for df in tv[a].values() if len(df) > 10] for a in algos}
    tpy_den = max(0.5, (rdata.lock_start - t0).days / 365.25)
    for a in algos:
        oos = res[a]["oos"]
        r = oos.r.to_numpy() if len(oos) else np.array([])
        row = {"oos": _summ(r)}
        ch = {c["variant"] for c in res[a]["chosen"] if c["variant"]}
        stress = {}
        for nm, kw in (("costs", {"cost_mult": COST_STRESS}), ("delay", {"delay": 1})):
            tv2 = run_variants(ctxs, [a], only={a: ch}, workers=1, **kw)[a] if ch else {}
            parts = []
            for c in res[a]["chosen"]:
                if c["variant"] and c["variant"] in tv2:
                    df = tv2[c["variant"]]
                    m = (df.entry_t.to_numpy() >= c["test_start"]) & (df.entry_t.to_numpy() < c["test_end"])
                    parts.append(df[m].r.to_numpy())
            stress[nm] = np.concatenate(parts) if parts else np.array([])
        mv = modal_variant(res[a]["chosen"])
        nb = []
        if mv:
            p0, e0 = parse_vkey(mv)
            for q in SCALP_ALGOS[a].neighbors(p0):
                df = tv[a].get(vkey(q, e0))
                if df is not None and len(df):
                    nb.append(st.expectancy(df.r.to_numpy()[in_windows(df.entry_t.to_numpy(), folds)]))
        row["modal_variant"] = mv
        tpy = len(r) / tpy_den if len(r) else 0
        g = cheap_gates(r, stress["costs"], nb, cfg, prof.max_loss_pct, tpy)
        g[f"g5_costs_x{COST_STRESS}"] = g.pop("g5_costs_x2")
        e_d = st.expectancy(stress["delay"]) if len(stress["delay"]) else float("nan")
        g["g10_delay_1_bar"] = (bool(e_d > 0), None if np.isnan(e_d) else round(e_d, 3), 0.0)
        trial_n = max(2, nvar[a] * len(dfs))
        dsr_p = st.deflated_sharpe(r, dsr_srs[a] or [0.0, 0.1], trial_n) if len(r) > 10 else 0.0
        row.update(gates={k: {"pass": bool(v[0]), "value": v[1], "threshold": v[2]} for k, v in g.items()},
                   dsr=round(dsr_p, 3), n_trials=trial_n, compliance=compliance(oos, tpy_den),
                   gross_expectancy_R=round(float(oos.gross_r.mean()), 3) if len(oos) else 0.0)
        res[a].update(row=row, gates=g, r=r)
    elig = [a for a in algos if all(v[0] for v in res[a]["gates"].values()) and res[a]["row"]["dsr"] >= cfg.dsr_min]
    if elig:
        jobs = [(a, *parse_vkey(res[a]["row"]["modal_variant"]), folds) for a in elig]
        log(f"[scalp] test nul ({null_B} surrogates) pour {elig}")
        nd = null_distribution(rdata.dfs, jobs, null_B, workers, news)
        for a in elig:
            obs = res[a]["row"]["oos"]["expectancy_R"]
            res[a]["gates"]["g4_null"] = null_gate(obs, nd[a][:, 0], n_tests, cfg)
            res[a]["row"]["null"] = {"obs": obs, "null_mean": round(float(nd[a][:, 0].mean()), 3),
                                     "null_p95": round(float(np.percentile(nd[a][:, 0], 95)), 3)}
    for a in algos:
        g, row = res[a]["gates"], res[a]["row"]
        g.setdefault("g4_null", (False, "non évalué (porte précédente échouée)", cfg.null_alpha))
        row["gates"] = {k: {"pass": bool(v[0]), "value": v[1], "threshold": v[2]} for k, v in g.items()}
        v, why = verdict(g, row["dsr"], years, cfg, row["oos"]["expectancy_R"])
        row["verdict"], row["reason"] = v, why
        row["target_math"] = target_math(row["oos"]["expectancy_R"], row["oos"]["n"], tpy_den, prof)
    rep["algos"] = {a: res[a]["row"] for a in algos}
    rep["hypotheses"] = {a: {"hypothese": SCALP_ALGOS[a].hypothesis, "invalidation": SCALP_ALGOS[a].invalidation} for a in algos}
    final_cfg = {a: res[a]["row"].get("modal_variant") for a in algos}
    rep["final_config"] = final_cfg
    if do_locked:
        def _ev(full, lock_start):
            cf = build_ctxs(full, news)
            out = {}
            for a in algos:
                mv = final_cfg.get(a)
                if not mv:
                    out[a] = {"n": 0, "note": "aucune variante sélectionnée"}; continue
                p0, e0 = parse_vkey(mv)
                parts = []
                for c in cf.values():
                    tr = sim_scalp(c, SCALP_ALGOS[a].generate(c, p0, SCALP_EXITS[e0]))
                    parts.append(tr[tr.entry_t >= lock_start.value].r.to_numpy())
                r = np.concatenate(parts)
                out[a] = {**_summ(r), "variant": mv, "verdict_research": rep["algos"][a]["verdict"]}
            return out
        rep["locked"] = final_evaluation(locked, _ev, out_dir, tag, force=locked_force)
        rep["locked"]["_note"] = "Configuration gelée avant lecture, évaluée UNE fois, publiée telle quelle."
    rep["runtime_s"] = round(time.time() - t_start, 1)
    rep["_internal"] = {"res": res}
    return rep
