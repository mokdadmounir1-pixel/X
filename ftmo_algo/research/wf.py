"""Exécution des variantes (algo × paramètres × sortie × instrument), walk-forward, surrogates du test nul."""
from __future__ import annotations
import multiprocessing as mp
import os
from dataclasses import dataclass, field, replace
import numpy as np
import pandas as pd
from ..algos.context import Ctx
from ..algos.library import ALGOS, EXIT_VARIANTS, exit_names
from ..data.quality import resample_ohlc
from ..engine.sim import Sim, SimConfig
from ..engine.guardian import PropProfile
from ..timeutil import ns

_G: dict = {}
KEEP = ["sym", "entry_t", "exit_t", "r", "gross_r", "grade", "mae_r", "mfe_r", "bars", "reason", "risk_usd", "pnl", "amb"]


def vkey(params: dict, exit_name: str) -> str:
    return "|".join(f"{k}={params[k]}" for k in sorted(params)) + "@" + exit_name


def dvkey(algo: str) -> str:
    """Clé de la variante PAR DÉFAUT d'un algo (paramètres par défaut, sa sortie par défaut)."""
    return vkey(ALGOS[algo].default, ALGOS[algo].default_exit)


def parse_vkey(k: str):
    p, e = k.split("@")
    params = {}
    for kv in p.split("|") if p else []:
        a, b = kv.split("=")
        params[a] = float(b) if "." in b else int(b)
    return params, e


def build_ctxs(dfs: dict, news=None, with_fine=True) -> dict[str, Ctx]:
    out = {}
    for sym, d in dfs.items():
        m15 = resample_ohlc(d, "M15")
        m15 = m15.drop(columns=["close_time"])
        m15.attrs.update(d.attrs)
        out[sym] = Ctx(sym, m15, news=news, fine=d if with_fine else None)
    return out


def sim_trades(ctx: Ctx, sig, cost_mult=1.0, risk_pct=0.5, grades=(2, 1, 0), ambiguity="stop", vol_slip=0.0) -> pd.DataFrame:
    cfg = SimConfig(risk_pct=risk_pct, cost_mult=cost_mult, use_guardian=False, grades=grades, ambiguity=ambiguity,
                    vol_slip=vol_slip)
    sim = Sim({ctx.sym: ctx.mk}, cfg, PropProfile())
    tr = sim.run([sig]).trades
    if len(tr) == 0:
        return pd.DataFrame(columns=KEEP + ["feat"])
    return tr[KEEP + ["feat"]]


def _task(args):
    algo, sym, cost_mult, only, grades = args
    ctx = _G["ctxs"][sym]
    a = ALGOS[algo]
    out = {}
    combos = a.combos() if a.grid else [a.default]
    exits = {k: EXIT_VARIANTS[k] for k in exit_names(algo)}
    for p in combos:
        todo = [e for e in exits if only is None or vkey(p, e) in only]
        if not todo:
            continue
        sig0 = a.generate(ctx, p, exits[todo[0]])      # les signaux ne dépendent pas de la sortie
        for e in todo:
            # « native » : l'algo porte SES sorties (SL/TP/BE/trailing/clôture de session) ; le catalogue ne les écrase pas
            sig = sig0 if e == "native" else replace(sig0, exit=exits[e])
            out[vkey(p, e)] = sim_trades(ctx, sig, cost_mult, grades=grades)
    return algo, sym, out


def run_variants(ctxs, algos, cost_mult=1.0, only=None, workers=1, grades=(2, 1, 0)) -> dict:
    """Retourne {algo: {vkey: DataFrame de trades (tous instruments)}}."""
    _G["ctxs"] = ctxs
    tasks = [(a, s, cost_mult, only.get(a) if isinstance(only, dict) else only, grades) for a in algos for s in ctxs]
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


# ---------------------------------------------------------------- walk-forward
@dataclass
class Fold:
    train_start: int
    test_start: int
    test_end: int


def make_folds(t0: pd.Timestamp, t1: pd.Timestamp, test_months=3, min_train_frac=0.34, min_train_months=9):
    span = t1 - t0
    first = max(t0 + pd.DateOffset(months=min_train_months), t0 + span * min_train_frac)
    folds = []
    s = first
    while s < t1:
        e = min(s + pd.DateOffset(months=test_months), t1)
        if (e - s).days >= 30:
            folds.append(Fold(t0.value, s.value, e.value))
        s = s + pd.DateOffset(months=test_months)
    return folds


def select_variant(trades_by_v: dict, fold: Fold, embargo_days=5, min_n=25, shrink=15, grade_min=0):
    best, best_s, info = None, -1e9, {}
    emb = embargo_days * 86_400 * 10**9
    for k, df in trades_by_v.items():
        if len(df) == 0:
            continue
        m = (df.entry_t.to_numpy() >= fold.train_start) & (df.exit_t.to_numpy() < fold.test_start - emb) \
            & (df.grade.to_numpy() >= grade_min)
        n = int(m.sum())
        if n < min_n:
            continue
        s = float(df.r.to_numpy()[m].sum() / (n + shrink))
        if s > best_s:
            best, best_s, info = k, s, {"train_n": n, "train_exp": float(df.r.to_numpy()[m].mean())}
    return best, info


def walk_forward(trades_by_v: dict, folds: list[Fold], grade_min=0, **kw):
    parts, chosen = [], []
    for i, f in enumerate(folds):
        k, info = select_variant(trades_by_v, f, grade_min=grade_min, **kw)
        chosen.append({"fold": i, "variant": k, **info, "test_start": f.test_start, "test_end": f.test_end})
        if k is None:
            continue
        df = trades_by_v[k]
        m = (df.entry_t.to_numpy() >= f.test_start) & (df.entry_t.to_numpy() < f.test_end) & (df.grade.to_numpy() >= grade_min)
        t = df[m].copy(); t["fold"] = i; t["variant"] = k
        parts.append(t)
    oos = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=KEEP + ["feat", "fold", "variant"])
    return oos, chosen


def modal_variant(chosen):
    from collections import Counter
    c = Counter(x["variant"] for x in chosen if x["variant"])
    return c.most_common(1)[0][0] if c else None


def in_windows(entry_t: np.ndarray, folds):
    m = np.zeros(len(entry_t), bool)
    for f in folds:
        m |= (entry_t >= f.test_start) & (entry_t < f.test_end)
    return m


# ---------------------------------------------------------------- surrogates (test nul)
def make_surrogate_stationary(df: pd.DataFrame, seed: int, mean_block=48) -> pd.DataFrame:
    """Bootstrap stationnaire des barres (écart, corps, mèches) par blocs de ~4 h, dérive retirée : détruit la structure
    au-delà du bloc (tendance multi-heures/jours, ordre des séances) en conservant la distribution des barres et la
    vol à l'intérieur des blocs. Complémentaire du test par inversion de signe (ne répond pas à la même question)."""
    from .stats import stationary_indices
    rng = np.random.default_rng(seed)
    o, h, l, c = (df[k].to_numpy("float64") for k in ("open", "high", "low", "close"))
    n = len(o)
    gap = np.r_[0.0, np.log(o[1:] / c[:-1])]
    body = np.log(c / o); up = np.log(h / o); dn = np.log(l / o)
    mu = (gap + body).mean()
    gap = gap - mu / 2; body = body - mu / 2
    idx = stationary_indices(n, n, mean_block, rng, 1)[0]
    gs, bs, ups, dns = gap[idx], body[idx], up[idx], dn[idx]
    lc = np.log(o[0]) + np.cumsum(gs + bs)
    lo_ = lc - bs
    out = df.copy()
    out["open"], out["close"] = np.exp(lo_), np.exp(lc)
    out["high"] = np.maximum(np.exp(lo_ + ups), np.maximum(out["open"], out["close"]))
    out["low"] = np.minimum(np.exp(lo_ + dns), np.minimum(out["open"], out["close"]))
    out.attrs.update(df.attrs); out.attrs["source"] = "SURROGATE(" + str(df.attrs.get("source")) + ")"
    return out


def shift_signals(sig, close: np.ndarray, k: int):
    """Décale les signaux de k barres en conservant leurs distances RELATIVES (stop/cible en % du prix de signal)."""
    from copy import copy
    n = len(sig.side)
    s2 = copy(sig)
    s2.side = np.zeros(n, np.int8); s2.stop = np.full(n, np.nan); s2.target = np.full(n, np.nan); s2.grade = np.zeros(n, np.int8)
    if sig.feat is not None:
        s2.feat = np.zeros_like(sig.feat)
    if sig.risk_mult is not None:
        s2.risk_mult = np.ones(n)
    if sig.xs is not None:
        s2.xs = np.zeros(n, np.int8)
    src = np.flatnonzero(sig.side != 0)
    dst = src + k
    ok = (dst >= 0) & (dst < n)
    src, dst = src[ok], dst[ok]
    s2.side[dst] = sig.side[src]; s2.grade[dst] = sig.grade[src]
    s2.stop[dst] = close[dst] * sig.stop[src] / close[src]
    s2.target[dst] = close[dst] * sig.target[src] / close[src]
    if sig.feat is not None:
        s2.feat[dst] = sig.feat[src]
    if sig.risk_mult is not None:
        s2.risk_mult[dst] = sig.risk_mult[src]
    if sig.xs is not None:
        okx = (np.flatnonzero(sig.xs != 0) + k)
        okx = okx[(okx >= 0) & (okx < n)]
        s2.xs[okx] = sig.xs[okx - k]
    return s2


def make_surrogate(df: pd.DataFrame, seed: int, demean=True) -> pd.DataFrame:
    """Inversion de signe aléatoire par blocs (1 jour) des rendements log, dérive retirée : détruit toute
    structure directionnelle exploitable en conservant volatilité, saisonnalité, spreads."""
    rng = np.random.default_rng(seed)
    o, h, l, c = (df[k].to_numpy("float64") for k in ("open", "high", "low", "close"))
    gap = np.r_[0.0, np.log(o[1:] / c[:-1])]
    body = np.log(c / o); up = np.log(h / o); dn = np.log(l / o)
    if demean:
        mu = (gap + body).mean()
        gap = gap - mu / 2; body = body - mu / 2
    day = ns(df.index) // 86_400_000_000_000
    _, blk = np.unique(day, return_inverse=True)
    s = rng.choice([-1.0, 1.0], size=blk.max() + 1)[blk]
    gs, bs = gap * s, body * s
    ups = np.where(s > 0, up, -dn); dns = np.where(s > 0, dn, -up)
    lc = np.log(o[0]) + np.cumsum(gs + bs)
    lo_ = lc - bs
    out = df.copy()
    out["open"], out["close"] = np.exp(lo_), np.exp(lc)
    out["high"] = np.maximum(np.exp(lo_ + ups), np.maximum(out["open"], out["close"]))   # cohérence OHLC après dérive retirée
    out["low"] = np.minimum(np.exp(lo_ + dns), np.minimum(out["open"], out["close"]))
    out.attrs.update(df.attrs); out.attrs["source"] = "SURROGATE(" + str(df.attrs.get("source")) + ")"
    return out


def cands_default(ctxs, algos, workers=1):
    """Candidats du filtre ML : chaque algo de base à ses paramètres PAR DÉFAUT (non optimisés) et sortie fixed3."""
    only = {a: {dvkey(a)} for a in algos if ALGOS[a].default}
    tr = run_variants(ctxs, list(only), only=only, workers=workers)
    parts = [df.assign(algo=a) for a in only for df in tr[a].values() if len(df)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=KEEP + ["feat", "algo"])


def _null_job(args):
    b, dfs, jobs, news, kind = args
    mk_s = make_surrogate_stationary if kind == "stationary" else make_surrogate
    ctxs = build_ctxs({s: mk_s(d, 7919 * b + i) for i, (s, d) in enumerate(dfs.items())}, news, with_fine=False)
    res = {}
    for (algo, params, ex, wins) in jobs:
        if algo == "ml_filter":
            from .ml import ml_filter
            base = [a for a in params]          # `params` porte ici la liste des algos candidats
            cands = cands_default(ctxs, base)
            kept, _, _ = ml_filter(cands, wins, base)
            r = kept.r.to_numpy() if len(kept) else np.array([])
            res[algo] = (float(r.mean()) if len(r) else 0.0, len(r))
            continue
        rs = []
        for s, ctx in ctxs.items():
            sig = ALGOS[algo].generate(ctx, params, EXIT_VARIANTS[ex])
            tr = sim_trades(ctx, sig)
            if len(tr):
                m = in_windows(tr.entry_t.to_numpy(), wins)
                rs.append(tr.r.to_numpy()[m])
        r = np.concatenate(rs) if rs else np.array([])
        res[algo] = (float(r.mean()) if len(r) else 0.0, len(r))
    return res


def null_distribution(dfs, jobs, B=99, workers=1, news=None, kind="signflip"):
    args = [(b, dfs, jobs, news, kind) for b in range(B)]
    if workers > 1:
        with mp.get_context("fork").Pool(workers) as pool:
            out = pool.map(_null_job, args, chunksize=1)
    else:
        out = [_null_job(a) for a in args]
    return {j[0]: np.array([o[j[0]] for o in out]) for j in jobs}   # (B, 2) : moyenne R, n trades


def compose_signals(ctx, algo, chosen, grade_min=0):
    """Signaux d'un algo sur un instrument, pli par pli (variante choisie sur l'entraînement), restreints aux
    fenêtres de test : même logique que le walk-forward, utilisée pour le portefeuille multi-instruments."""
    out = []
    a = ALGOS[algo]
    for c in chosen:
        if not c.get("variant"):
            continue
        p, e = parse_vkey(c["variant"])
        sig = a.generate(ctx, p, EXIT_VARIANTS[e])
        t = ctx.mk.t
        m = (t >= c["test_start"]) & (t < c["test_end"]) & (sig.grade >= grade_min)
        sig.side = np.where(m, sig.side, 0).astype("int8")
        if (sig.side != 0).any():
            out.append(sig)
    return out


def portfolio_sim(ctxs, chosen_by_algo, members, risk_pct=0.5, cost_mult=1.0, grade_min=0, profile=None):
    """Simulation PORTEFEUILLE multi-instruments avec gardien, plafond de risque par groupe corrélé et arrêt
    sur perte journalière. Les gardiens bloquent mais ne coupent pas la simulation (mesure de l'effet)."""
    sigs = []
    for algo in members:
        for sym, ctx in ctxs.items():
            sigs += compose_signals(ctx, algo, chosen_by_algo[algo], grade_min)
    cfg = SimConfig(risk_pct=risk_pct, cost_mult=cost_mult, grades=(2, 1, 0), stop_on_breach=False)
    sim = Sim({s: c.mk for s, c in ctxs.items()}, cfg, profile or PropProfile())
    res = sim.run(sigs)
    return res
