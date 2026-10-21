"""Les algos orientés gros RR. Chacun : hypothèse économique, invalidation, génération CAUSALE
(le signal en i n'utilise que des données clôturées ≤ i)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .base import Algo, Signals, ExitCfg, empty_signals
from .context import Ctx


def clip_stop(c, stop, side, atr, lo, hi):
    d = np.clip(np.abs(c - stop), lo * atr, hi * atr)
    return c - side * d


def grade(score):
    return np.where(score >= 4, 2, np.where(score >= 3, 1, 0)).astype("int8")


def _finish(ctx: Ctx, name, side, stop, score, ex, target=None, level_dist=None, **kw) -> Signals:
    s = empty_signals(name, ctx.sym, ctx.n, ex, **kw)
    ok = (side != 0) & np.isfinite(stop)
    ok[:250] = False                       # échauffement des indicateurs
    s.side = np.where(ok, side, 0).astype("int8")
    s.stop = np.where(ok, stop, np.nan)
    if target is not None:
        s.target = np.where(ok, target, np.nan)
    s.grade = np.where(ok, grade(score), 0).astype("int8")
    s.feat = ctx.features(s.side.astype("float32"), s.stop, level_dist)
    s.feat_names = Ctx.FEAT_NAMES
    return s


def _common_score(ctx, side, extra=0):
    sc = ((ctx.h1_trend == side).astype(int) + (ctx.h4_trend == side).astype(int)
          + ((ctx.vol_ratio > 0.7) & (ctx.vol_ratio < 1.8)).astype(int)
          + ((ctx.since_news > 90) & (ctx.until_news > 120)).astype(int))
    return sc + extra


class TrendPullback(Algo):
    name = "trend_pullback"
    hypothesis = ("Les tendances H1/H4 persistent (flux institutionnels étalés dans le temps) ; un repli vers la "
                  "moyenne H1 ou un niveau clé puis la reprise de la structure M15 offre un stop court et un gros RR.")
    invalidation = "ADX H1 < 15 (pas de tendance), tendance H4 contraire, repli qui casse la structure H1."
    grid = {"pull_n": [6, 12, 20], "stop_atr": [1.0, 1.5, 2.0]}
    default = {"pull_n": 12, "stop_atr": 1.5}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        c, h, l, o, atr = ctx.c, ctx.h, ctx.l, ctx.o, ctx.atr
        n = p["pull_n"]
        side = np.zeros(ctx.n, np.int8)
        hh = pd.Series(h).rolling(n).max().shift(1).to_numpy()   # extrêmes AVANT la barre i
        ll = pd.Series(l).rolling(n).min().shift(1).to_numpy()
        near = np.abs(c - ctx.h1_ema20) < 1.0 * atr
        up = (ctx.h1_trend > 0) & (ctx.h4_trend >= 0) & (ctx.h1_adx > 18)
        dn = (ctx.h1_trend < 0) & (ctx.h4_trend <= 0) & (ctx.h1_adx > 18)
        pulled_dn = (ll < pd.Series(c).shift(n).to_numpy()) & (l.min() < c)      # repli récent
        retr_up = (pd.Series(h).rolling(n).max().to_numpy() - pd.Series(l).rolling(n).min().to_numpy()) > 0
        prev_c = np.r_[np.nan, c[:-1]]
        prev_h = np.r_[np.nan, h[:-1]]; prev_l = np.r_[np.nan, l[:-1]]
        pullback_long = (c < pd.Series(c).rolling(n).max().shift(1).to_numpy() - 0.8 * atr)
        pullback_short = (c > pd.Series(c).rolling(n).min().shift(1).to_numpy() + 0.8 * atr)
        long = up & near & pullback_long & (c > o) & (c > prev_h) & (c > ctx.ema20)
        short = dn & near & pullback_short & (c < o) & (c < prev_l) & (c < ctx.ema20)
        side[long] = 1; side[short] = -1
        raw = np.where(side > 0, np.minimum(ll, l) - 0.2 * atr, np.where(side < 0, np.maximum(hh, h) + 0.2 * atr, np.nan))
        stop = clip_stop(c, raw, side, atr, p["stop_atr"], p["stop_atr"] + 1.0)
        lvl = np.where(side > 0, c - np.fmax(ctx.pd_low, ctx.h1_ema50), np.fmax(ctx.pd_high, ctx.h1_ema50) - c) / atr
        score = _common_score(ctx, side, (np.abs(lvl) < 1.0).astype(int))
        return _finish(ctx, self.name, side, stop, score, ex, level_dist=np.abs(lvl))


class SweepReversal(Algo):
    name = "sweep_reversal"
    hypothesis = ("Les stops au-dessus/dessous des extrêmes de veille/semaine/Asie sont des réservoirs de liquidité ; "
                  "un balayage suivi d'un rejet (mèche + clôture de retour) trahit une prise de liquidité sans suite.")
    invalidation = "Clôture au-delà du niveau balayé, tendance H1 forte (ADX>35) dans le sens du balayage."
    grid = {"wick_k": [0.4, 0.8, 1.2], "stop_atr": [0.8, 1.2, 1.6]}
    default = {"wick_k": 0.8, "stop_atr": 1.2}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        c, h, l, o, atr = ctx.c, ctx.h, ctx.l, ctx.o, ctx.atr
        side = np.zeros(ctx.n, np.int8)
        his = [ctx.pd_high, ctx.wk_high, ctx.asia_high]
        los = [ctx.pd_low, ctx.wk_low, ctx.asia_low]
        sw_hi = np.zeros(ctx.n, bool); sw_lo = np.zeros(ctx.n, bool); big = np.zeros(ctx.n, int)
        for k, (H, L) in enumerate(zip(his, los)):
            hh = np.nan_to_num(H, nan=1e18); ll = np.nan_to_num(L, nan=-1e18)
            a = (h > hh) & (c < hh) & ((h - np.maximum(o, c)) > p["wick_k"] * atr)
            b = (l < ll) & (c > ll) & ((np.minimum(o, c) - l) > p["wick_k"] * atr)
            sw_hi |= a; sw_lo |= b; big += ((a | b) & (k < 2))
        calm = ctx.h1_adx < 35
        side[sw_hi & calm & (c < o)] = -1
        side[sw_lo & calm & (c > o)] = 1
        raw = np.where(side < 0, h + 0.1 * atr, np.where(side > 0, l - 0.1 * atr, np.nan))
        stop = clip_stop(c, raw, side, atr, p["stop_atr"], p["stop_atr"] + 1.2)
        room = np.where(side < 0, c - ctx.pd_low, ctx.pd_high - c) / np.abs(c - stop)
        score = _common_score(ctx, -side * 0 + side, 0) * 0 + (big > 0).astype(int) + (room > 3).astype(int) \
            + (ctx.h1_adx < 25).astype(int) + ((ctx.vol_ratio > 0.7) & (ctx.vol_ratio < 1.8)).astype(int)
        return _finish(ctx, self.name, side, stop, score, ex, level_dist=np.zeros(ctx.n))


class SqueezeBreakout(Algo):
    name = "squeeze_breakout"
    hypothesis = ("La compression de volatilité accumule des ordres ; son expansion s'accompagne de mouvements "
                  "directionnels étendus que l'on capte avec un stop court et un trailing.")
    invalidation = "Cassure sans expansion de range (faux départ), retour dans la boîte en < 4 barres."
    grid = {"squeeze_q": [0.10, 0.20, 0.30], "donch_n": [20, 40, 60]}
    default = {"squeeze_q": 0.2, "donch_n": 40}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        c, h, l, o, atr = ctx.c, ctx.h, ctx.l, ctx.o, ctx.atr
        n = p["donch_n"]
        bw = pd.Series(ctx.bb_bw)
        q = bw.rolling(480, min_periods=120).quantile(p["squeeze_q"]).shift(1)
        squeezed = (bw.shift(1) <= q).rolling(8, min_periods=1).max().fillna(0).to_numpy() > 0
        dh = pd.Series(h).rolling(n).max().shift(1).to_numpy(); dl = pd.Series(l).rolling(n).min().shift(1).to_numpy()
        expand = (h - l) > 1.0 * atr
        side = np.zeros(ctx.n, np.int8)
        side[squeezed & expand & (c > dh) & (c > o)] = 1
        side[squeezed & expand & (c < dl) & (c < o)] = -1
        mid = pd.Series(c).rolling(20).mean().to_numpy()
        stop = clip_stop(c, mid, side, atr, 1.0, 2.5)
        score = _common_score(ctx, side, (ctx.h1_adx > 20).astype(int))
        return _finish(ctx, self.name, side, stop, score, ex, level_dist=np.zeros(ctx.n))


class SessionORB(Algo):
    name = "session_orb"
    hypothesis = ("L'ouverture de la séance principale concentre des flux ; la cassure de la plage d'ouverture "
                  "en régime directionnel prolonge le déséquilibre. (A déjà échoué hors échantillon : aucune "
                  "faveur, doit refaire sa preuve.)")
    invalidation = "Régime de range (ADX H1 < seuil), cassure puis réintégration de la plage."
    grid = {"range_min": [30, 60, 90], "adx_min": [15, 20, 25]}
    default = {"range_min": 60, "adx_min": 20}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        c, h, l, o, atr = ctx.c, ctx.h, ctx.l, ctx.o, ctx.atr
        so = ctx.spec.session_open[0] * 60 + ctx.spec.session_open[1]
        rel = ctx.local_min - so                                  # minutes depuis l'ouverture locale
        in_rng = (rel >= 0) & (rel < p["range_min"])
        df = pd.DataFrame({"h": np.where(in_rng, h, np.nan), "l": np.where(in_rng, l, np.nan), "d": ctx.local_day})
        rh = df.groupby("d")["h"].cummax().groupby(df["d"]).ffill().to_numpy()
        rl = df.groupby("d")["l"].cummin().groupby(df["d"]).ffill().to_numpy()
        after = (rel >= p["range_min"]) & (rel < p["range_min"] + 240)
        side = np.zeros(ctx.n, np.int8)
        reg = (ctx.h1_adx >= p["adx_min"]) & (ctx.vol_ratio > 0.8)
        side[after & reg & (c > rh) & (c > o)] = 1
        side[after & reg & (c < rl) & (c < o)] = -1
        # première cassure du jour seulement
        d = pd.Series(side != 0).groupby(ctx.local_day).cumsum().to_numpy()
        side = np.where(d == 1, side, 0).astype(np.int8)
        raw = np.where(side > 0, rl, np.where(side < 0, rh, np.nan))
        stop = clip_stop(c, raw, side, atr, 1.0, 3.0)
        score = _common_score(ctx, side, ((rh - rl) / atr < 4).astype(int))
        return _finish(ctx, self.name, side, stop, score, ex, level_dist=np.zeros(ctx.n), max_per_day=1)


class MeanReversionZ(Algo):
    name = "meanrev_z"
    hypothesis = ("En régime de range (ADX bas), les excès extrêmes autour du VWAP ancré sont des déséquilibres "
                  "de liquidité temporaires qui reviennent vers la valeur ; le RR dépend de la distance au VWAP.")
    invalidation = "ADX H1 qui monte, z qui continue à s'étendre (tendance naissante), annonce proche."
    grid = {"z_thr": [2.0, 2.5, 3.0], "adx_max": [18, 22, 26]}
    default = {"z_thr": 2.5, "adx_max": 22}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        c, h, l, o, atr = ctx.c, ctx.h, ctx.l, ctx.o, ctx.atr
        z = ctx.sessions_vwap_z(); vw = ctx._vw
        prev_z = np.r_[np.nan, z[:-1]]
        rng = (ctx.h1_adx < p["adx_max"]) & (ctx.until_news > 120) & (ctx.since_news > 90)
        side = np.zeros(ctx.n, np.int8)
        side[rng & (prev_z < -p["z_thr"]) & (c > o)] = 1
        side[rng & (prev_z > p["z_thr"]) & (c < o)] = -1
        raw = np.where(side > 0, np.minimum(l, np.r_[l[0], l[:-1]]) - 0.3 * atr,
                       np.where(side < 0, np.maximum(h, np.r_[h[0], h[:-1]]) + 0.3 * atr, np.nan))
        stop = clip_stop(c, raw, side, atr, 0.8, 2.0)
        target = np.where(side != 0, vw, np.nan)
        score = _common_score(ctx, side * 0, (ctx.h1_adx < 18).astype(int) + (np.abs(prev_z) > p["z_thr"] + .5).astype(int)) \
            - (ctx.h1_trend == -side).astype(int) * 0
        return _finish(ctx, self.name, side, stop, score, ex, target=target, level_dist=np.abs(z))


class NewsMomentum(Algo):
    name = "news_momentum"
    hypothesis = ("Après une annonce majeure, la réaction initiale (spread élargi, prix chaotique) est suivie d'un "
                  "drift dans le même sens quand l'information est digérée ; on entre APRÈS la réaction, jamais avant.")
    invalidation = "Retournement complet de la réaction (clôture de retour dans la bougie d'annonce)."
    grid = {"delay": [1, 2, 3], "move_k": [1.0, 1.5, 2.0]}
    default = {"delay": 2, "move_k": 1.5}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        c, h, l, o, atr = ctx.c, ctx.h, ctx.l, ctx.o, ctx.atr
        side = np.zeros(ctx.n, np.int8); stop = np.full(ctx.n, np.nan)
        mk = ctx.mk
        for t_ev in ctx.news.t:
            i0 = int(np.searchsorted(mk.t, t_ev, side="right")) - 1     # barre contenant l'annonce
            if i0 < 1 or i0 + p["delay"] >= ctx.n:
                continue
            i = i0 + p["delay"]                                          # décision à la clôture de i
            move = c[i] - o[i0]
            if abs(move) >= p["move_k"] * atr[i0] and (mk.t[i] - t_ev) < 3 * 3600e9:
                s = 1 if move > 0 else -1
                ext = np.min(l[i0:i + 1]) if s > 0 else np.max(h[i0:i + 1])
                side[i] = s; stop[i] = ext - s * 0.1 * atr[i]
        stop = np.where(side != 0, clip_stop(c, np.nan_to_num(stop, nan=c), side, atr, 1.0, 3.0), np.nan)
        score = np.where(side != 0, 3 + (ctx.h1_trend == side).astype(int), 0)
        return _finish(ctx, self.name, side, stop, score, ex, level_dist=np.zeros(ctx.n), allow_news=True, max_per_day=1)


class RegimeRouter(Algo):
    name = "regime_router"
    hypothesis = ("Aucun setup n'a d'edge dans tous les régimes : tendance -> continuation/compression ; range -> "
                  "retour à la moyenne/balayage ; choc d'annonce -> momentum ; sinon NO TRADE.")
    invalidation = "Le routage n'améliore pas l'espérance OOS par rapport aux algos pris seuls."
    grid = {"adx_trend": [22, 28], "adx_range": [16, 20]}
    default = {"adx_trend": 25, "adx_range": 18}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        trend = (ctx.h1_adx >= p["adx_trend"]) & (ctx.vol_ratio < 2.2)
        rng = (ctx.h1_adx <= p["adx_range"])
        shock = (ctx.since_news < 180)
        parts = []
        for cls, mask in ((TrendPullback, trend), (SqueezeBreakout, trend), (SweepReversal, rng),
                          (MeanReversionZ, rng), (NewsMomentum, shock)):
            a = cls()
            s = a.generate(ctx, a.default, ex)
            s.side = np.where(mask, s.side, 0).astype("int8")
            parts.append(s)
        out = empty_signals(self.name, ctx.sym, ctx.n, ex)
        out.feat = parts[0].feat.copy(); out.feat_names = parts[0].feat_names
        for s in parts:
            free = (out.side == 0) & (s.side != 0)
            out.side[free] = s.side[free]; out.stop[free] = s.stop[free]; out.target[free] = s.target[free]
            out.grade[free] = s.grade[free]; out.feat[free] = s.feat[free]
        out.allow_news = True
        return out


class MLFilter(Algo):
    """Méta-algo : ne génère aucun signal propre, FILTRE ceux des autres (voir research.ml)."""
    name = "ml_filter"
    hypothesis = ("Les setups des algos de base ont une qualité hétérogène ; un modèle logistique walk-forward "
                  "(labels triple-barrière au RR cible, purge + embargo) peut écarter les contextes perdants.")
    invalidation = "L'espérance OOS filtrée n'est pas supérieure à l'espérance OOS non filtrée."
    grid: dict = {}
    default: dict = {}
    meta = True


ALGOS = {c.name: c() for c in (TrendPullback, SweepReversal, SqueezeBreakout, SessionORB, MeanReversionZ,
                              NewsMomentum, RegimeRouter, MLFilter)}
BASE_ALGOS = [n for n, a in ALGOS.items() if not getattr(a, "meta", False)]
EXIT_VARIANTS = {
    "fixed3": ExitCfg("fixed", rr=3.0, time_stop=96),
    "fixed4": ExitCfg("fixed", rr=4.0, time_stop=96),
    "fixed3_wkflat": ExitCfg("fixed", rr=3.0, time_stop=96, weekend_flat=True),   # fermeture avant week-end
    "be3": ExitCfg("be", rr=3.0, time_stop=96, be_at=1.0),
    "partial4": ExitCfg("partial", rr=4.0, time_stop=96, partial_at=1.5, partial_frac=0.5),
    "trail_atr": ExitCfg("trail_atr", rr=8.0, time_stop=192, atr_k=2.5, trail_after=1.0),
    "trail_struct": ExitCfg("trail_struct", rr=8.0, time_stop=192, trail_after=1.0),
}
