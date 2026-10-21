"""Algos scalp M1. Chacun : hypothèse économique, invalidation, grille. Signal à la clôture de i, exécution à l'ouverture de i+1.
Filtres communs : fenêtres liquides fixes, coût aller-retour ≤ COST_FRAC × distance de stop (le scalp ne se joue pas si les coûts
mangent le stop), échauffement."""
from __future__ import annotations
from dataclasses import replace
import numpy as np
import pandas as pd
from ..algos.base import Algo, Signals, ExitCfg, empty_signals
from .ctx import ScalpCtx, WARMUP

COST_FRAC = 0.25          # [HYPOTHÈSE] a priori, non optimisé : coût A/R ≤ 25 % de la distance de stop (≈ −0,25 R de frottement max)

SCALP_EXITS = {
    "s15": ExitCfg("fixed", rr=1.5, time_stop=20),
    "s2": ExitCfg("fixed", rr=2.0, time_stop=30),
    "s3": ExitCfg("fixed", rr=3.0, time_stop=45),
    "sbe2": ExitCfg("be", rr=2.0, time_stop=30, be_at=1.0),
}


def _finish(ctx: ScalpCtx, name, side, stop, ex, target=None, max_per_day=4, params=None) -> Signals:
    ok = (side != 0) & np.isfinite(stop) & ctx.liquid
    ok[:WARMUP] = False
    dist = np.abs(ctx.c - np.nan_to_num(stop, nan=ctx.c))
    ok &= (dist > 0) & (ctx.rt_cost <= COST_FRAC * dist)
    s = empty_signals(name, ctx.sym, ctx.n, ex, max_per_day=max_per_day, params=params or {})
    s.side = np.where(ok, side, 0).astype("int8")
    s.stop = np.where(ok, stop, np.nan)
    if target is not None:
        s.target = np.where(ok, target, np.nan)
    s.grade = np.where(ok, 1, 0).astype("int8")
    return s


def _clip_stop(c, raw, side, atr, lo, hi):
    return c - side * np.clip(np.abs(c - raw), lo * atr, hi * atr)


class OpenRangeBreak(Algo):
    name = "orb_micro"
    hypothesis = ("L'ouverture de la séance concentre les ordres institutionnels : la sortie de la fourchette des premières minutes "
                  "avec élan déclenche des stops et prolonge le mouvement quelques dizaines de minutes.")
    invalidation = "Faux départs systématiques (retour dans la fourchette), spread élargi à l'ouverture > 25 % du stop."
    grid = {"or_min": [15, 30], "stop_atr": [2.0, 3.0]}
    default = {"or_min": 15, "stop_atr": 2.0}
    timeframes = ("M1",)

    def generate(self, ctx: ScalpCtx, p: dict, ex: ExitCfg) -> Signals:
        so = ctx.since_open
        d = pd.DataFrame({"h": ctx.h, "l": ctx.l, "g": ctx.local_day})
        inr = (so >= 0) & (so < p["or_min"])
        orh = d["h"].where(inr).groupby(d["g"]).cummax().groupby(d["g"]).ffill().to_numpy()
        orl = d["l"].where(inr).groupby(d["g"]).cummin().groupby(d["g"]).ffill().to_numpy()
        live = (so >= p["or_min"]) & (so < p["or_min"] + 120)
        pc = np.r_[np.nan, ctx.c[:-1]]
        buf = 0.1 * ctx.atr
        long = live & (ctx.c > orh + buf) & (pc <= orh + buf)
        short = live & (ctx.c < orl - buf) & (pc >= orl - buf)
        side = np.zeros(ctx.n, np.int8)
        side[long] = 1; side[short] = -1
        stop = ctx.c - side * p["stop_atr"] * ctx.atr
        return _finish(ctx, self.name, side, np.where(side != 0, stop, np.nan), ex, params=p)


class VwapFade(Algo):
    name = "vwap_fade"
    hypothesis = ("Dans un marché sans tendance, les écarts extrêmes au VWAP de séance (flux de liquidité non informé) se résorbent ; "
                  "on achète le retournement d'un écart > k écarts-types avec la cible au VWAP.")
    invalidation = "Efficacité de tendance élevée (le prix s'éloigne sans revenir) ou spread > 25 % du stop."
    grid = {"zk": [2.0, 2.5, 3.0], "er_max": [0.25, 0.40]}
    default = {"zk": 2.5, "er_max": 0.25}
    timeframes = ("M1",)

    def generate(self, ctx: ScalpCtx, p: dict, ex: ExitCfg) -> Signals:
        z, vw = ctx.vwap_z()
        c, o = ctx.c, ctx.o
        net = np.abs(c - pd.Series(c).shift(30).to_numpy())
        path = pd.Series(np.abs(np.r_[0.0, np.diff(c)])).rolling(30).sum().to_numpy()
        er = net / np.maximum(path, 1e-12)
        ok = (ctx.since_open >= 45) & (er < p["er_max"]) & np.isfinite(z)
        long = ok & (z < -p["zk"]) & (c > o)
        short = ok & (z > p["zk"]) & (c < o)
        side = np.zeros(ctx.n, np.int8)
        side[long] = 1; side[short] = -1
        lo3 = pd.Series(ctx.l).rolling(3).min().to_numpy() - 0.25 * ctx.atr
        hi3 = pd.Series(ctx.h).rolling(3).max().to_numpy() + 0.25 * ctx.atr
        raw = np.where(side > 0, lo3, np.where(side < 0, hi3, np.nan))
        stop = np.where(side != 0, _clip_stop(c, raw, side, ctx.atr, 1.0, 3.0), np.nan)
        tgt = np.where(side != 0, vw, np.nan)
        return _finish(ctx, self.name, side, stop, ex, target=tgt, params=p)


class RangeBurst(Algo):
    name = "burst_momentum"
    hypothesis = ("Une barre d'expansion (amplitude ≫ ATR, clôture à l'extrême, volume anormal) trahit un déséquilibre d'ordres "
                  "qui se prolonge quelques minutes (exécution fractionnée des gros ordres).")
    invalidation = "Retour systématique dans la barre d'expansion (épuisement) ; spread élargi pendant l'expansion."
    grid = {"k": [2.5, 3.5], "vol_k": [0.0, 1.5]}
    default = {"k": 2.5, "vol_k": 0.0}
    timeframes = ("M1",)

    def generate(self, ctx: ScalpCtx, p: dict, ex: ExitCfg) -> Signals:
        c, o, h, l = ctx.c, ctx.o, ctx.h, ctx.l
        rng = h - l
        big = rng >= p["k"] * ctx.atr_prev
        volok = (ctx.vol >= p["vol_k"] * np.nan_to_num(ctx.vol_med, nan=1e18)) if p["vol_k"] > 0 else np.ones(ctx.n, bool)
        pos = (c - l) / np.maximum(rng, 1e-12)
        long = big & volok & (pos >= 0.8) & (c > o)
        short = big & volok & (pos <= 0.2) & (c < o)
        side = np.zeros(ctx.n, np.int8)
        side[long] = 1; side[short] = -1
        raw_d = np.maximum(1.0 * ctx.atr_prev, 0.5 * rng)
        stop = np.where(side != 0, c - side * np.clip(raw_d, 1.0 * ctx.atr_prev, 3.0 * ctx.atr_prev), np.nan)
        return _finish(ctx, self.name, side, stop, ex, params=p)


class MicroSweep(Algo):
    name = "micro_sweep"
    hypothesis = ("Les stops sous/sur les extrêmes récents (20-40 min) sont un réservoir de liquidité ; un balayage avec longue mèche "
                  "et retour au-dessus du niveau signale une prise de liquidité sans suite.")
    invalidation = "Le prix reclôture au-delà du niveau balayé (cassure réelle) ; mèches dues au seul élargissement du spread."
    grid = {"n": [20, 40], "wick_k": [0.5, 1.0]}
    default = {"n": 20, "wick_k": 0.5}
    timeframes = ("M1",)

    def generate(self, ctx: ScalpCtx, p: dict, ex: ExitCfg) -> Signals:
        c, o, h, l = ctx.c, ctx.o, ctx.h, ctx.l
        n = p["n"]
        pl = pd.Series(l).rolling(n).min().shift(1).to_numpy()
        ph = pd.Series(h).rolling(n).max().shift(1).to_numpy()
        lw = np.minimum(o, c) - l
        uw = h - np.maximum(o, c)
        long = (l < pl) & (c > pl) & (lw >= p["wick_k"] * ctx.atr_prev)
        short = (h > ph) & (c < ph) & (uw >= p["wick_k"] * ctx.atr_prev)
        side = np.zeros(ctx.n, np.int8)
        side[long] = 1; side[short] = -1
        raw = np.where(side > 0, l - 0.2 * ctx.atr_prev, np.where(side < 0, h + 0.2 * ctx.atr_prev, np.nan))
        stop = np.where(side != 0, _clip_stop(c, raw, side, ctx.atr_prev, 0.8, 2.5), np.nan)
        return _finish(ctx, self.name, side, stop, ex, params=p)


SCALP_ALGOS = {a.name: a for a in (OpenRangeBreak(), VwapFade(), RangeBurst(), MicroSweep())}


def delay_signals(sig: Signals, k: int = 1) -> Signals:
    """Latence : le signal n'est exécutable que k barres plus tard (stress délibérément dur : M1 ne résout pas la sous-minute)."""
    out = replace(sig)
    for f in ("side", "stop", "target", "grade"):
        a = getattr(sig, f)
        b = np.empty_like(a)
        b[:k] = 0 if f in ("side", "grade") else np.nan
        b[k:] = a[:-k]
        setattr(out, f, b)
    return out
