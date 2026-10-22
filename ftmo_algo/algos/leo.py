"""Algos portés des EA MT5 de Leo (formation « Algo Rentable ») : Range Breakout, Bandito, Happy Gold, Double
Croisement, Hybride MM/SuperTrend, Cloud EMA/ATR, Gold Scalping et les 6 modules du SuperSelector (+ le sélecteur).

Principe de fidélité : la LOGIQUE D'ENTRÉE, les distances SL/TP, le break-even/trailing, les filtres et les horaires
(heure SERVEUR) sont ceux des EA. Ce qui change, volontairement, c'est l'exécution : tout passe par le moteur pessimiste
du projet (signal à la clôture de la barre M15, fill à l'ouverture suivante, bid/ask, slippage, commissions, swaps, stop
prioritaire). Un ordre stop MT5 est donc approximé par « clôture au-delà du niveau puis fill à l'ouverture suivante ».
Les protections d'exécution MT5 (verrous fichier, refus compte réel, reprise sur historique…) n'ont pas d'objet dans un
moteur de simulation et ne sont pas portées. Écarts détaillés, algo par algo : `LEO.md`.

Causalité : à l'indice i, rien ne dépend de données postérieures à la clôture de i (test_causality s'applique à tous).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .base import Algo, Signals, ExitCfg, empty_signals
from .context import Ctx
from ..data.quality import align_htf
from ..indicators import ema_arr
from ..timeutil import SERVER_TZ, server_clock

WARM = 250                       # échauffement minimal (barres M15) avant tout signal
NS_MIN = 60_000_000_000


# ============================================================================ outils communs
def _cache(ctx, key, fn):
    d = ctx.__dict__.setdefault("_leo_cache", {})
    if key not in d:
        d[key] = fn()
    return d[key]


def srv_open(ctx):
    """(minute du jour, jour de semaine, identifiant de jour) en heure serveur à l'OUVERTURE de chaque barre."""
    return _cache(ctx, "srv_open", lambda: server_clock(ctx.mk.t))


def bar_minutes(ctx) -> int:
    return max(1, int(round(ctx.mk.bar_ns() / NS_MIN)))


def server_bars(ctx, tf: str):
    """Barres D1 / W1 / H12 ancrées sur MINUIT SERVEUR (comme le terminal MT5 du courtier), construites depuis la base M15.
    Retourne (DataFrame indexé par l'ouverture avec `close_time`, indices alignés SANS FUITE : dernière barre déjà close)."""
    def build():
        mk = ctx.mk
        omin, _, oday = srv_open(ctx)
        if tf == "D1":
            key, close_min = oday, (oday + 1) * 1440
        elif tf == "W1":
            key = (oday + 3) // 7                                   # semaines lundi->dimanche (jour 0 = jeudi 1970-01-01)
            close_min = ((key + 1) * 7 - 3) * 1440
        elif tf == "H12":
            half = (omin >= 720).astype(np.int64)
            key, close_min = oday * 2 + half, oday * 1440 + (half + 1) * 720
        else:
            raise ValueError(tf)
        g = pd.DataFrame({"o": mk.o, "h": mk.h, "l": mk.l, "c": mk.c, "t": mk.t, "k": key, "cm": close_min})
        a = g.groupby("k", sort=True).agg(open=("o", "first"), high=("h", "max"), low=("l", "min"), close=("c", "last"),
                                          t=("t", "first"), cm=("cm", "first"))
        ct = pd.to_datetime(a["cm"].to_numpy() * 60, unit="s").tz_localize(SERVER_TZ).tz_convert("UTC")
        out = pd.DataFrame({"open": a["open"].to_numpy(), "high": a["high"].to_numpy(), "low": a["low"].to_numpy(),
                            "close": a["close"].to_numpy()}, index=pd.to_datetime(a["t"].to_numpy(), utc=True))
        out["close_time"] = ct
        return out, align_htf(mk.tc, out)
    return _cache(ctx, "sb_" + tf, build)


def al(ix, arr, fill=np.nan):
    return Ctx._al(ix, arr, fill)


def true_range(h, l, c):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    tr[0] = h[0] - l[0]
    return tr


def atr_sma(h, l, c, n):
    """ATR « iATR » de MT5 : moyenne SIMPLE du true range."""
    return pd.Series(true_range(h, l, c)).rolling(n).mean().to_numpy()


def atr_wilder(h, l, c, n, skip_first=False):
    """ATR de Wilder amorcé par la moyenne simple des n premiers TR (comme les EA Cloud / Hybride)."""
    tr = true_range(h, l, c)
    out = np.full(len(c), np.nan)
    a = 1 if skip_first else 0
    if len(c) < n + a:
        return out
    out[n - 1 + a] = tr[a:n + a].mean()
    for i in range(n + a, len(c)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def supertrend(h, l, c, atr, mult):
    """SuperTrend à bandes à cliquet ; +1 haussier, -1 baissier, 0 tant que l'ATR n'est pas valide. Récursion causale."""
    n = len(c)
    trend = np.zeros(n, np.int8)
    init, up, lo, tr = False, 0.0, 0.0, 0
    for i in range(n):
        a = atr[i]
        if not (np.isfinite(a) and a > 0):
            continue
        hl2 = (h[i] + l[i]) / 2.0
        bu, bl = hl2 + mult * a, hl2 - mult * a
        if not init:
            up, lo, tr, init = bu, bl, (1 if c[i] >= hl2 else -1), True
        else:
            pc = c[i - 1]
            nu = bu if (bu < up or pc > up) else up
            nl = bl if (bl > lo or pc < lo) else lo
            if tr == 1 and c[i] < nl:
                tr = -1
            elif tr == -1 and c[i] > nu:
                tr = 1
            up, lo = nu, nl
        trend[i] = tr
    return trend


def pivot_confirms(h, l, nl, nr):
    """Pivots fractals STRICTS (nl barres à gauche, nr à droite) : indices de CONFIRMATION (clôture de la barre s+nr) et
    niveaux. Aucune donnée postérieure à l'indice de confirmation n'intervient."""
    n = len(h)
    sh, sl = pd.Series(h), pd.Series(l)
    pre_h = sh.rolling(nl).max().shift(1).to_numpy(); pre_l = sl.rolling(nl).min().shift(1).to_numpy()
    post_h = sh.rolling(nr).max().to_numpy(); post_l = sl.rolling(nr).min().to_numpy()   # fenêtre s+1..s+nr lue en s+nr
    hs, ls = np.full(n, np.nan), np.full(n, np.nan)
    ph, pl = np.full(n, np.nan), np.full(n, np.nan)
    if n > nr:
        hs[nr:], ls[nr:], ph[nr:], pl[nr:] = h[:-nr], l[:-nr], pre_h[:-nr], pre_l[:-nr]
    with np.errstate(invalid="ignore"):
        ch = np.flatnonzero((hs > ph) & (hs > post_h))
        cl = np.flatnonzero((ls < pl) & (ls < post_l))
    return ch, hs[ch], cl, ls[cl]


def _first(arr, start, trig, limit, op):
    seg = arr[start:limit]
    if len(seg) == 0:
        return -1
    m = {"ge": seg >= trig, "le": seg <= trig, "gt": seg > trig, "lt": seg < trig}[op]
    k = int(np.argmax(m))
    return start + k if m[k] else -1


def breaks_touch(h, l, c, conf, lv, up, off, scan):
    """Happy Gold : le DERNIER pivot confirmé porte l'ordre stop ; il est remplacé dès qu'un nouveau pivot est confirmé.
    Premier contact du niveau dans la barre j (consommation) ; trade seulement si la barre CLÔTURE au-delà (ordre stop
    approximé), sinon niveau consommé sans trade. Retourne (masque des barres de cassure, niveau déclencheur)."""
    n = len(c)
    sig = np.zeros(n, bool)
    trg = np.full(n, np.nan)
    for t in range(len(conf)):
        ik = int(conf[t])
        trig = lv[t] + off if up else lv[t] - off
        lim = min(n, ik + 1 + scan)
        if t + 1 < len(conf):
            lim = min(lim, int(conf[t + 1]) + 1)              # remplacé à la confirmation du pivot suivant
        j = _first(h if up else l, ik + 1, trig, lim, "ge" if up else "le")
        if j >= 0 and (c[j] >= trig if up else c[j] <= trig):
            sig[j] = True
            trg[j] = trig
    return sig, trg


def breaks_cross(c, conf, lv, up, off, lookback, nr):
    """Gold Scalping : tout pivot confirmé non consommé est surveillé ; première CLÔTURE au-delà du niveau (le pivot est
    consommé à ce moment, avant tout filtre). Âge maximal du pivot : `lookback` barres."""
    n = len(c)
    sig = np.zeros(n, bool)
    for t in range(len(conf)):
        ik = int(conf[t])
        trig = lv[t] + off if up else lv[t] - off
        lim = min(n, ik - nr + lookback + 1)
        j = _first(c, ik + 1, trig, lim, "gt" if up else "lt")
        if j >= 0:
            sig[j] = True
    return sig


def in_schedule(ctx, start_min, end_min, fri_end_min=None, days=(0, 1, 2, 3, 4)):
    """Horaire en heure serveur évalué À LA CLÔTURE de la barre (= instant de décision)."""
    mk = ctx.mk
    end = np.where(mk.srv_dow_c == 4, fri_end_min if fri_end_min is not None else end_min, end_min)
    return (mk.srv_min_c >= start_min) & (mk.srv_min_c < end) & np.isin(mk.srv_dow_c, days)


def decision_bars(ctx, minute, days=(0, 1, 2, 3, 4)):
    """Barre dont la clôture tombe à `minute` (heure serveur) : une décision par jour, jamais de rattrapage."""
    mk = ctx.mk
    return (mk.srv_min_c == minute) & np.isin(mk.srv_dow_c, days)


def _build(ctx: Ctx, name, side, stop, ex, target=None, level_dist=None, grade=2, **kw) -> Signals:
    s = empty_signals(name, ctx.sym, ctx.n, ex, **kw)
    ok = (side != 0) & np.isfinite(stop)
    ok[:WARM] = False
    with np.errstate(invalid="ignore"):
        ok &= np.where(side > 0, stop < ctx.c, stop > ctx.c)       # le stop doit être du bon côté du prix
    s.side = np.where(ok, side, 0).astype("int8")
    s.stop = np.where(ok, stop, np.nan)
    if target is not None:
        s.target = np.where(ok, target, np.nan)
    s.grade = np.where(ok, np.broadcast_to(grade, ctx.n), 0).astype("int8")
    s.feat = ctx.features(s.side.astype("float32"), s.stop, level_dist)
    s.feat_names = Ctx.FEAT_NAMES
    return s


class LeoAlgo(Algo):
    family = "leo"
    exits = ("native",)          # sorties de l'EA, non remplacées par le catalogue de sorties du projet
    default_exit = "native"
    source = ""                  # fichier MT5 d'origine


# ============================================================================ 01 Range Breakout
class LeoRangeBreakout(LeoAlgo):
    name = "leo_range_breakout"
    source = "01_Range_Breakout.mq5"
    native_symbols = ("XAUUSD", "US30", "US100", "USDJPY", "BTCUSD")
    hypothesis = ("[Leo 01] La plage 00:00-07:30 (heure serveur) résume la session calme ; sa cassure par la suite de la "
                  "journée engage un déséquilibre. Un seul sens par jour (premier déclenché), SL au bord opposé ou en %, "
                  "aucun TP, clôture à 18:00, jamais d'overnight.")
    invalidation = "Plage trop étroite/large, faux départs (retour dans la plage), régime sans directionnalité intrajournalière."
    grid = {"end_min": [360, 450, 540], "sl_pct": [0.0, 0.5, 1.0]}
    default = {"end_min": 450, "sl_pct": 0.0}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        c = ctx.c
        step = bar_minutes(ctx)
        omin, _, oday = srv_open(ctx)
        end, delete = int(p["end_min"]), 18 * 60
        inw = (omin >= 0) & (omin + step <= end)
        d = pd.DataFrame({"day": oday, "h": np.where(inw, ctx.h, np.nan), "l": np.where(inw, ctx.l, np.nan), "w": inw.astype(int)})
        g = d.groupby("day")
        hi, lo = g["h"].transform("max").to_numpy(), g["l"].transform("min").to_numpy()
        cnt = g["w"].transform("sum").to_numpy()
        need = int(np.ceil(end / step * 0.90))                      # MinBarsPct = 90 %
        off = ctx.spec.tick                                         # EntryOffsetPoints = 1
        good = (omin >= end) & (omin + step <= delete) & (cnt >= need) & np.isfinite(hi) & np.isfinite(lo) & (hi > lo)
        up, dn = good & (c > hi + off), good & (c < lo - off)
        cand = up | dn
        first = cand & (pd.Series(cand.astype(int)).groupby(oday).cumsum().to_numpy() == 1)   # première cassure du jour
        side = np.where(first & up, 1, np.where(first & dn, -1, 0)).astype(np.int8)
        pct = float(p["sl_pct"]) / 100.0
        if pct == 0.0:
            stop = np.where(side > 0, lo, np.where(side < 0, hi, np.nan))
        else:
            stop = np.where(side > 0, (hi + off) * (1 - pct), np.where(side < 0, (lo - off) * (1 + pct), np.nan))
        lvl = np.where(side > 0, hi + off, lo - off)
        e = ExitCfg("fixed", rr=20.0, time_stop=0, flat_srv_min=delete)    # pas de TP : sortie par stop ou 18:00
        return _build(ctx, self.name, side, stop, e, level_dist=np.abs(c - lvl) / ctx.atr, max_per_day=1)


# ============================================================================ 02 Bandito
class LeoBandito(LeoAlgo):
    name = "leo_bandito"
    source = "02_Bandito.mq5"
    native_symbols = ("AUDCAD",)
    hypothesis = ("[Leo 02] Retour à la moyenne sur Bollinger(20, 2σ) en H1 : la PREMIÈRE clôture hors bande est un excès "
                  "qui revient (achat sous la bande basse, vente au-dessus de la haute). SL 180 pips, TP 130 pips, trailing, "
                  "sortie sur bande ou MM50. RR natif < 1 : l'edge repose sur le taux de réussite, pas sur le RR.")
    invalidation = "Marché en tendance (les excès continuent), spread > 3 pips, coûts qui rongent un RR de 0,72."
    grid = {"bb_dev": [1.5, 2.0, 2.5], "tp_pips": [100, 130, 160]}
    default = {"bb_dev": 2.0, "tp_pips": 130}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        mk, c = ctx.mk, ctx.c
        h1, ix1 = ctx.h1, ctx.ix1
        cl = h1.close.to_numpy()
        sma = pd.Series(cl).rolling(20).mean().to_numpy()
        sd = pd.Series(cl).rolling(20).std(ddof=0).to_numpy()
        dev, devx = float(p["bb_dev"]), 2.0
        lo_e, up_e = sma - dev * sd, sma + dev * sd
        lo_x, up_x = sma - devx * sd, sma + devx * sd
        ma50 = pd.Series(cl).rolling(50).mean().to_numpy()
        prev = lambda x: np.r_[np.nan, x[:-1]]
        with np.errstate(invalid="ignore"):
            buy_k = (cl < lo_e) & (prev(cl) > prev(lo_e))                  # première clôture sous la bande basse
            sell_k = (cl > up_e) & (prev(cl) < prev(up_e))
            xl_k = (cl > up_x) | (cl > ma50)                               # sorties : bande haute ou MM50 (longs)
            xs_k = (cl < lo_x) | (cl < ma50)
        newbar = (ix1 != np.r_[-2, ix1[:-1]]) & (ix1 >= 1)                 # décision à la clôture d'une barre H1
        A = lambda x: al(ix1, x.astype("float64"), 0.0) > 0.5
        pip = ctx.spec.tick * 10.0
        spr_ok = mk.spr <= 3.0 * pip                                       # MaxSpread = 3 pips
        side = np.where(newbar & spr_ok & A(buy_k), 1, np.where(newbar & spr_ok & A(sell_k), -1, 0)).astype(np.int8)
        xs = (np.where(newbar & A(xl_k), 1, 0) | np.where(newbar & A(xs_k), 2, 0)).astype(np.int8)
        tp = float(p["tp_pips"]) * pip
        stop = c - side * 180.0 * pip
        target = c + side * tp
        e = ExitCfg("fixed", rr=1.0, time_stop=0, px_trail_start=10.0 * pip, px_trail_dist=180.0 * pip, px_trail_step=0.0)
        return _build(ctx, self.name, side, stop, e, target=target, level_dist=np.zeros(ctx.n), max_per_day=3,
                      min_rr_net=0.0, xs=xs)


# ============================================================================ 03 Happy Gold
class LeoHappyGold(LeoAlgo):
    name = "leo_happy_gold"
    source = "03_Happy_Gold.mq5"
    native_symbols = ("XAUUSD",)
    hypothesis = ("[Leo 03] Cassure du dernier pivot fractal confirmé (N barres closes de chaque côté) : le niveau d'un "
                  "extrême confirmé concentre des stops, sa cassure déclenche un mouvement. SL 240 pts, TP 1000 pts, "
                  "break-even à +10 pts, trailing 20 pts, session 03:00-19:00 (vendredi 12:00), long seul par défaut.")
    invalidation = "Faux départs sur l'extrême, spread > 35 pts, trailing de 20 pts balayé par le bruit intrabar."
    grid = {"n_conf": [8, 12, 16], "direction": [0, 1, 2]}
    default = {"n_conf": 12, "direction": 0}            # direction : 0 long, 1 short, 2 les deux

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        mk, c, h, l = ctx.mk, ctx.c, ctx.h, ctx.l
        n, pt = int(p["n_conf"]), ctx.spec.tick
        chi, lvh, clo, lvl_ = pivot_confirms(h, l, n, n)
        up, trig_u = breaks_touch(h, l, c, chi, lvh, True, 0.0, 300)
        dn, trig_d = breaks_touch(h, l, c, clo, lvl_, False, 0.0, 300)
        sess = in_schedule(ctx, 3 * 60, 19 * 60, fri_end_min=12 * 60) & (mk.spr <= 35.0 * pt)   # InpSpreadMaxPoints = 35
        want_up, want_dn = int(p["direction"]) in (0, 2), int(p["direction"]) in (1, 2)
        up, dn = up & sess & want_up, dn & sess & want_dn
        side = np.where(up & ~dn, 1, np.where(dn & ~up, -1, 0)).astype(np.int8)
        trig = np.where(side > 0, trig_u, trig_d)                  # niveau du pivot cassé (prix de l'ordre stop)
        stop = trig - side * 240.0 * pt
        target = trig + side * 1000.0 * pt
        e = ExitCfg("fixed", rr=4.0, time_stop=0, flat_srv_min=19 * 60, flat_fri_srv_min=12 * 60,
                    px_be_trig=10.0 * pt, px_be_lock=0.0, px_trail_start=20.0 * pt, px_trail_dist=20.0 * pt,
                    px_trail_step=0.0, px_trail_above_entry=True)
        return _build(ctx, self.name, side, stop, e, target=target, level_dist=np.abs(c - trig) / ctx.atr, max_per_day=3)


# ============================================================================ 04 Double Croisement
class LeoDoubleCroisement(LeoAlgo):
    name = "leo_double_croisement"
    source = "04_Double_Croisement.mq5"
    native_symbols = ("GER40", "US30", "US500", "US100", "XAUUSD")
    hypothesis = ("[Leo 04] Achat intrajournalier long seul filtré par DEUX ÉTATS haussiers (EMA 4/29 hebdo et EMA 10/15 "
                  "quotidienne) : on n'achète que quand la tendance lente ET la tendance rapide sont alignées. Décision "
                  "01:00 serveur, SL = 2×ATR D1, clôture forcée 21:30.")
    invalidation = "Retournement hebdo, croisement D1 baissier, gaps overnight contre la position, ATR D1 trop petit pour les coûts."
    grid = {"sl_atr": [1.5, 2.0, 3.0], "d_slow": [15, 20, 25]}
    default = {"sl_atr": 2.0, "d_slow": 15}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        c = ctx.c
        w1, ixw = server_bars(ctx, "W1")
        d1, ixd = server_bars(ctx, "D1")
        wc = w1.close.to_numpy()
        wf, ws = al(ixw, ema_arr(wc, 4)), al(ixw, ema_arr(wc, 29))
        dc = d1.close.to_numpy()
        df_, ds = al(ixd, ema_arr(dc, 10)), al(ixd, ema_arr(dc, int(p["d_slow"])))
        atr = al(ixd, atr_sma(d1.high.to_numpy(), d1.low.to_numpy(), dc, 14))
        valid = (ixw >= 3 * 29) & np.isfinite(atr) & (atr > 0)
        with np.errstate(invalid="ignore"):
            buy = decision_bars(ctx, 60) & valid & (wf > ws) & (df_ > ds)
        side = np.where(buy, 1, 0).astype(np.int8)
        stop = c - float(p["sl_atr"]) * atr
        e = ExitCfg("fixed", rr=20.0, time_stop=0, flat_srv_min=21 * 60 + 30)
        return _build(ctx, self.name, side, stop, e, level_dist=np.zeros(ctx.n), max_per_day=1)


# ============================================================================ 05 Hybride MM + SuperTrend
class LeoHybrideSuperTrend(LeoAlgo):
    name = "leo_hybride_supertrend"
    source = "05_Hybride_MM_SuperTrend.mq5"
    native_symbols = ("GER40", "US30", "US500", "US100", "XAUUSD")
    hypothesis = ("[Leo 05] Achat intrajournalier long seul : tendance hebdo (EMA 4/29) ET SuperTrend D1 (ATR 10, ×3) "
                  "haussiers. Le SuperTrend remplace le croisement D1 comme confirmation de tendance. Décision 01:00, "
                  "SL = 2×ATR D1 (Wilder), clôture 21:30.")
    invalidation = "SuperTrend qui bascule souvent (range), tendance hebdo tardive, gaps overnight."
    grid = {"st_mult": [2.0, 3.0, 4.0], "sl_atr": [1.5, 2.0, 2.5]}
    default = {"st_mult": 3.0, "sl_atr": 2.0}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        c = ctx.c
        w1, ixw = server_bars(ctx, "W1")
        d1, ixd = server_bars(ctx, "D1")
        wc = w1.close.to_numpy()
        wf, ws = al(ixw, ema_arr(wc, 4)), al(ixw, ema_arr(wc, 29))
        h, l, dc = d1.high.to_numpy(), d1.low.to_numpy(), d1.close.to_numpy()
        atr_w = atr_wilder(h, l, dc, 10, skip_first=True)
        st = al(ixd, supertrend(h, l, dc, atr_w, float(p["st_mult"])).astype("float64"), 0.0)
        atr = al(ixd, atr_w)
        valid = (ixw >= 3 * 29) & np.isfinite(atr) & (atr > 0)
        with np.errstate(invalid="ignore"):
            buy = decision_bars(ctx, 60) & valid & (wf > ws) & (st > 0)
        side = np.where(buy, 1, 0).astype(np.int8)
        stop = c - float(p["sl_atr"]) * atr
        e = ExitCfg("fixed", rr=20.0, time_stop=0, flat_srv_min=21 * 60 + 30)
        return _build(ctx, self.name, side, stop, e, level_dist=np.zeros(ctx.n), max_per_day=1)


# ============================================================================ 07 Cloud EMA/ATR
CLOUD_PRESETS = {   # fastW, slowW, atrW, nTight, seuil, fastD, slowD
    0: (4, 29, 10, 3, 0.1222, 10, 15),      # Cloud H12
    1: (3, 25, 20, 2, 0.3174, 13, 18),      # GER40
    2: (4, 25, 14, 2, 0.2666, 13, 15),      # DJ30
}


def cloud_step(s: dict, bull: bool, P: bool, D: bool, H: bool, use_h12: bool = True) -> bool:
    """Machine asymétrique de l'EA Cloud (mise à jour une fois par décision). `lastBuy` = décision, pas exécution."""
    if bull:
        if s["prevSet"] and not s["prevReg"]:
            s["locked"] = s["episode"] = s["susp"] = False
        if P:
            s["susp"] = not (D or (use_h12 and H))
        buy = not s["susp"]
    else:
        if s["prevSet"] and s["prevReg"]:
            s["susp"] = False
        if P and not s["prevP"]:
            s["episode"], s["locked"] = True, False
        buy = False
        if s["locked"]:
            pass
        elif s["episode"]:
            if D:
                buy = True
            elif s["lastBuy"]:
                s["locked"], s["episode"] = True, False
    s["prevReg"], s["prevSet"], s["prevP"], s["lastBuy"] = bull, True, P, buy
    return buy


class LeoCloudEmaAtr(LeoAlgo):
    name = "leo_cloud_ema_atr"
    source = "07_Cloud_EMA_ATR.mq5"
    native_symbols = ("GER40", "US30")
    hypothesis = ("[Leo 07] Moteur Cloud : l'écart EMA/ATR hebdomadaire (« nuage ») et sa vitesse de resserrement ouvrent ou "
                  "ferment un portail ; une machine à états asymétrique (régime hausse/baisse, suspension, rebond baissier, "
                  "verrou) décide l'achat quotidien. Presets Cloud H12 / GER40 / DJ30. SL = ATR D1 × mult, clôture 21:45.")
    invalidation = "Le portail ne prédit pas les retournements ; état dépendant de l'historique (une dérive fausse toute la suite)."
    grid = {"preset": [0, 1, 2], "sl_atr": [1.0, 1.5, 2.0]}
    default = {"preset": 0, "sl_atr": 1.5}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        c = ctx.c
        fW, sW, aW, nT, thr, fD, sD = CLOUD_PRESETS[int(p["preset"])]
        w1, ixw = server_bars(ctx, "W1")
        d1, ixd = server_bars(ctx, "D1")
        h12, ixh = server_bars(ctx, "H12")
        wh, wl, wc = (w1[k].to_numpy() for k in ("high", "low", "close"))
        d = (ema_arr(wc, fW) - ema_arr(wc, sW)) / atr_wilder(wh, wl, wc, aW)
        d_n = np.r_[np.full(nT, np.nan), d[:-nT]] if len(d) > nT else np.full(len(d), np.nan)
        R = (np.abs(d_n) - np.abs(d)) / nT
        valid_w = np.isfinite(d) & np.isfinite(R)
        dcl = d1.close.to_numpy()
        Dcross = ema_arr(dcl, fD) >= ema_arr(dcl, sD)
        hcl = h12.close.to_numpy()
        Hcross = ema_arr(hcl, 10) >= ema_arr(hcl, 15)
        bullM = al(ixw, (d >= 0).astype("float64"), 0.0) > 0.5
        PM = al(ixw, (R >= thr).astype("float64"), 0.0) > 0.5
        okM = al(ixw, valid_w.astype("float64"), 0.0) > 0.5
        DM = al(ixd, Dcross.astype("float64"), 0.0) > 0.5
        HM = al(ixh, Hcross.astype("float64"), 0.0) > 0.5
        atr = al(ixd, atr_wilder(d1.high.to_numpy(), d1.low.to_numpy(), dcl, 14))
        dec = decision_bars(ctx, 90) & okM & (ixw >= 3 * sW) & np.isfinite(atr) & (atr > 0)
        st = dict(susp=False, locked=False, episode=False, prevSet=False, prevReg=False, prevP=False, lastBuy=False)
        buy = np.zeros(ctx.n, bool)
        for i in np.flatnonzero(dec):               # une décision par jour, état persistant (séquentiel, causal)
            buy[i] = cloud_step(st, bool(bullM[i]), bool(PM[i]), bool(DM[i]), bool(HM[i]))
        side = np.where(buy, 1, 0).astype(np.int8)
        stop = c - float(p["sl_atr"]) * atr
        e = ExitCfg("fixed", rr=20.0, time_stop=0, flat_srv_min=21 * 60 + 45)
        return _build(ctx, self.name, side, stop, e, level_dist=np.zeros(ctx.n), max_per_day=1)


# ============================================================================ 08 Gold Scalping
class LeoGoldScalping(LeoAlgo):
    name = "leo_gold_scalping"
    source = "08_Gold_Scalping.mq5"
    native_symbols = ("XAUUSD",)
    hypothesis = ("[Leo 08] Variante à pivots fractals confirmés (3 barres de chaque côté) : première CLÔTURE au-delà d'un "
                  "pivot non consommé, filtrée par ADX ≥ 25 et SuperTrend H1 (ATR 10, ×3) dans le sens du trade ; les deux "
                  "sens sont permis. SL 240 pts, TP 1000 pts, BE à +100 pts (verrou 10), trailing 200 pts (pas 20), "
                  "fenêtre 03:00-19:00 serveur avec clôture hors fenêtre.")
    invalidation = "ADX bas (range), SuperTrend H1 contraire, spread moyen > 35 pts, pivots consommés par le bruit."
    grid = {"piv": [3, 5, 8], "adx_min": [20.0, 25.0, 30.0]}
    default = {"piv": 3, "adx_min": 25.0}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        mk, c, h, l = ctx.mk, ctx.c, ctx.h, ctx.l
        n, pt = int(p["piv"]), ctx.spec.tick
        chi, lvh, clo, lvl_ = pivot_confirms(h, l, n, n)
        up = breaks_cross(c, chi, lvh, True, 0.0, 300, n)
        dn = breaks_cross(c, clo, lvl_, False, 0.0, 300, n)
        # filtres appliqués APRÈS la consommation du pivot (comme l'EA)
        h1, ix1 = ctx.h1, ctx.ix1
        h1h, h1l, h1c = (h1[k].to_numpy() for k in ("high", "low", "close"))
        trend = al(ix1, supertrend(h1h, h1l, h1c, atr_sma(h1h, h1l, h1c, 10), 3.0).astype("float64"), 0.0)
        win = in_schedule(ctx, 3 * 60, 19 * 60)
        ok = win & (mk.spr <= 35.0 * pt) & (ctx.adx >= float(p["adx_min"]))
        up, dn = up & ok & (trend > 0), dn & ok & (trend < 0)
        side = np.where(up & ~dn, 1, np.where(dn & ~up, -1, 0)).astype(np.int8)
        stop = c - side * 240.0 * pt
        target = c + side * 1000.0 * pt
        e = ExitCfg("fixed", rr=4.0, time_stop=0, flat_srv_min=19 * 60,
                    px_be_trig=100.0 * pt, px_be_lock=10.0 * pt, px_trail_start=0.0, px_trail_dist=200.0 * pt,
                    px_trail_step=20.0 * pt, px_trail_above_entry=True)
        return _build(ctx, self.name, side, stop, e, target=target, level_dist=np.zeros(ctx.n), max_per_day=3)


# ============================================================================ SuperSelector : 6 modules + sélecteur
def _ss_base(ctx: Ctx):
    """Séries communes aux modules (M15) ; r1 = barre i (dernière close), r2 = i-1, etc."""
    def build():
        o, h, l, c = ctx.o, ctx.h, ctx.l, ctx.c
        atr = atr_sma(h, l, c, 14)
        vol = ctx.df["volume"].to_numpy("float64")
        sh = lambda x, k: np.r_[np.full(k, np.nan), x[:-k]] if k > 0 else x
        return dict(o=o, h=h, l=l, c=c, atr=atr, vol=vol, sh=sh, body=np.abs(c - o),
                    spr_ok=ctx.mk.spr <= 80.0 * ctx.spec.tick, dow=ctx.mk.srv_dow_c)
    return _cache(ctx, "ss_base", build)


def _ss_monday(ctx):
    b = _ss_base(ctx); sh = b["sh"]; c, o, atr = b["c"], b["o"], b["atr"]
    buy = c > o
    fast, slow = ctx.h1_ema20, ctx.h1_ema50
    with np.errstate(invalid="ignore"):
        score = (60.0 + np.where((buy & (fast > slow)) | (~buy & (fast < slow)), 15.0, 0.0)
                 + np.where(b["body"] > 0.5 * atr, 10.0, 0.0) + np.where(b["vol"] > sh(b["vol"], 1), 5.0, 0.0))
        fire = (b["dow"] == 0) & (b["body"] > 0) & np.isfinite(atr) & np.isfinite(fast) & np.isfinite(slow) & (score >= 70.0)
    return np.where(fire, np.where(buy, 1, -1), 0).astype(np.int8), score, atr


def _ss_lcrb(ctx):
    b = _ss_base(ctx); sh = b["sh"]; c, o, h, l, atr = b["c"], b["o"], b["h"], b["l"], b["atr"]
    sd = pd.Series(c).rolling(20).std(ddof=0).to_numpy()
    W = 4.0 * sd                                                       # largeur BB(20, 2σ) = haute - basse
    width = sh(W, 1)                                                   # EA : bande au shift 2 (= barre i-1)
    avgw = pd.Series(W).rolling(10).mean().shift(2).to_numpy()         # shifts 3..12
    rh = pd.Series(h).rolling(9).max().shift(1).to_numpy(); rl = pd.Series(l).rolling(9).min().shift(1).to_numpy()   # r[2..10]
    with np.errstate(invalid="ignore"):
        comp = (avgw > 0) & (width <= avgw * 0.85)
        disp = b["body"] >= 0.55 * atr
        sw_lo = (l < rl) & (c > rl); sw_hi = (h > rh) & (c < rh)
        buy, sell = sw_lo & (c > o), sw_hi & (c < o)
        score = (70.0 + np.where(width < avgw * 0.70, 8.0, 0.0) + np.where(b["body"] > 0.8 * atr, 8.0, 0.0)
                 + np.where(b["vol"] > sh(b["vol"], 1), 4.0, 0.0))
        fire = comp & disp & (buy | sell) & np.isfinite(atr) & (score >= 70.0)
    return np.where(fire, np.where(buy, 1, -1), 0).astype(np.int8), score, atr


def _ss_volshock(ctx):
    b = _ss_base(ctx); sh = b["sh"]; c, o, atr = b["c"], b["o"], b["atr"]
    atr3 = sh(atr, 2)
    with np.errstate(invalid="ignore"):
        shock = (atr3 > 0) & (atr >= 1.15 * atr3) & (b["body"] >= 0.45 * atr)
        prior_dn, prior_up = sh(c, 1) < sh(o, 1), sh(c, 1) > sh(o, 1)
        buy = prior_dn & (c > o) & (c > sh(c, 1)); sell = prior_up & (c < o) & (c < sh(c, 1))
        score = 70.0 + np.where(atr > 1.4 * atr3, 10.0, 0.0) + np.where(b["body"] > 0.8 * atr, 7.0, 0.0)
        fire = shock & (buy | sell) & (score >= 70.0)
    return np.where(fire, np.where(buy, 1, -1), 0).astype(np.int8), score, atr


def _ss_ldr(ctx):
    b = _ss_base(ctx); sh = b["sh"]; c, o, h, l, atr = b["c"], b["o"], b["h"], b["l"], b["atr"]
    avg = pd.Series(h - l).rolling(7).mean().shift(2).to_numpy()       # r[3..9]
    with np.errstate(invalid="ignore"):
        big = (avg > 0) & ((h - l) >= 1.2 * avg)
        buy = (sh(l, 1) < sh(l, 2)) & (c > sh(h, 1)) & (c > o)
        sell = (sh(h, 1) > sh(h, 2)) & (c < sh(l, 1)) & (c < o)
        fire = big & (buy | sell) & np.isfinite(atr)
    return np.where(fire, np.where(buy, 1, -1), 0).astype(np.int8), np.full(ctx.n, 72.0), atr


def _ss_ibi(ctx):
    b = _ss_base(ctx); sh = b["sh"]; c, o, atr = b["c"], b["o"], b["atr"]
    # NB : l'EA ne vérifie pas que r[2] est une inside bar, seulement que son range est <= 0,8 ATR (port fidèle)
    with np.errstate(invalid="ignore"):
        small = (sh(b["h"], 1) - sh(b["l"], 1)) <= 0.8 * atr
        buy = (c > sh(b["h"], 1)) & (c > o); sell = (c < sh(b["l"], 1)) & (c < o)
        fire = small & (buy | sell) & (b["body"] >= 0.5 * atr) & np.isfinite(atr)
    return np.where(fire, np.where(buy, 1, -1), 0).astype(np.int8), np.full(ctx.n, 71.0), atr


def _ss_eef(ctx):
    b = _ss_base(ctx); sh = b["sh"]; c, o, atr = b["c"], b["o"], b["atr"]
    with np.errstate(invalid="ignore"):
        ext = np.abs(sh(c, 1) - sh(c, 7)) >= 2.0 * atr
        buy = (sh(c, 1) < sh(o, 1)) & (c > o) & (c > sh(b["h"], 1))
        sell = (sh(c, 1) > sh(o, 1)) & (c < o) & (c < sh(b["l"], 1))
        fire = ext & (buy | sell) & np.isfinite(atr)
    return np.where(fire, np.where(buy, 1, -1), 0).astype(np.int8), np.full(ctx.n, 70.0), atr


CORE_RISK, EXP_RISK = 0.35, 0.15                                       # CoreRiskPct / ExperimentalRiskPct de l'EA
SS_MODULES = {   # nom -> (fonction, SL×ATR, TP×ATR, coeur ?)
    "monday": (_ss_monday, 1.2, 2.0, True),
    "lcrb": (_ss_lcrb, 1.2, 2.0, False),
    "volshock": (_ss_volshock, 1.3, 2.0, False),
    "ldr": (_ss_ldr, 1.3, 2.2, False),
    "ibi": (_ss_ibi, 1.2, 2.0, False),
    "eef": (_ss_eef, 1.4, 2.2, False),
}


def _ss_signals(ctx, name, side, score, atr, sl_k, tp_k, core, min_score=70.0):
    b = _ss_base(ctx)
    c = ctx.c
    side = np.where((score >= min_score) & b["spr_ok"], side, 0).astype(np.int8)
    stop = c - side * sl_k * atr
    target = c + side * tp_k * atr
    risk = np.full(ctx.n, 1.0 if core else EXP_RISK / CORE_RISK)
    e = ExitCfg("fixed", rr=2.0, time_stop=0)
    return _build(ctx, name, side, stop, e, target=target, level_dist=np.zeros(ctx.n), grade=2 if core else 1,
                  max_per_day=5, min_rr_net=0.0, risk_mult=risk)


class _SSModule(LeoAlgo):
    source = "SuperSelector_MT5_FINAL.mq5"
    module = ""
    timeframes = ("M15",)

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        fn, _, _, core = SS_MODULES[self.module]
        side, score, atr = fn(ctx)
        return _ss_signals(ctx, self.name, side, score, atr, float(p["sl_k"]), float(p["tp_k"]), core)


def _ss_class(module, title, hyp, inv, sl, tp):
    return type(f"LeoSS_{module}", (_SSModule,), dict(
        name=f"leo_ss_{module}", module=module, hypothesis=f"[Leo SuperSelector — {title}] {hyp}", invalidation=inv,
        grid={"sl_k": [round(sl - 0.2, 2), sl, round(sl + 0.3, 2)], "tp_k": [round(tp - 0.5, 2), tp, round(tp + 0.5, 2)]},
        default={"sl_k": sl, "tp_k": tp}))


LeoSSMonday = _ss_class("monday", "MondayMomentum",
                        "Le lundi (heure serveur), l'impulsion directionnelle M15 alignée sur les EMA 20/50 H1 prolonge le "
                        "flux de début de semaine. Palier « coeur » (risque plein). SL 1,2 ATR, TP 2,0 ATR.",
                        "Lundi sans suite, alignement H1 qui s'inverse, corps de bougie sans signification.", 1.2, 2.0)
LeoSSLcrb = _ss_class("lcrb", "LCRB",
                      "Compression Bollinger puis balayage d'un extrême récent avec retour (reclaim) et bougie de "
                      "déplacement : prise de liquidité sans suite. Palier expérimental. SL 1,2 ATR, TP 2,0 ATR.",
                      "Compression sans expansion, balayage qui continue (cassure réelle).", 1.2, 2.0)
LeoSSVolShock = _ss_class("volshock", "VolatilityShock",
                          "Un choc de volatilité (ATR en hausse de 15 % vs 3 barres plus tôt) suivi d'une bougie de "
                          "retournement confirmée tend à se normaliser. Palier expérimental. SL 1,3 ATR, TP 2,0 ATR.",
                          "Le choc est le début d'un régime de volatilité durable.", 1.3, 2.0)
LeoSSLdr = _ss_class("ldr", "LDR",
                     "Liquidity Displacement Reversal : balayage du plus bas/haut de la barre précédente puis clôture "
                     "au-delà de son extrême opposé avec un range ≥ 1,2× la moyenne. Palier expérimental. SL 1,3, TP 2,2 ATR.",
                     "Retournement sans volume réel, range moyen non représentatif.", 1.3, 2.2)
LeoSSIbi = _ss_class("ibi", "IBI",
                     "Compression (range de la barre précédente ≤ 0,8 ATR) puis cassure impulsive à corps ≥ 0,5 ATR. "
                     "Port fidèle : l'EA ne teste pas la condition d'inside bar. Palier expérimental. SL 1,2, TP 2,0 ATR.",
                     "Cassure sans suite, compression qui n'est qu'un range banal.", 1.2, 2.0)
LeoSSEef = _ss_class("eef", "EEF",
                     "Extreme Extension Failure : après une extension ≥ 2 ATR sur 6 barres, une bougie de retour qui "
                     "dépasse l'extrême de la précédente signale l'échec. Palier expérimental. SL 1,4, TP 2,2 ATR.",
                     "L'extension est une tendance qui s'accélère, pas un excès.", 1.4, 2.2)


class LeoSuperSelector(LeoAlgo):
    """Le sélecteur de l'EA : pour chaque barre, le PREMIER module qui signale dans l'ordre de priorité de l'EA
    (Monday, LCRB, VolShock, LDR, IBI, EEF) ; paliers de risque core/expérimental ; score minimal."""
    name = "leo_superselector"
    source = "SuperSelector_MT5_FINAL.mq5"
    timeframes = ("M15",)
    hypothesis = ("[Leo SuperSelector] Scanner/sélecteur adaptatif : six modules en priorité fixe, score minimal, palier de "
                  "risque coeur (Monday, 0,35 %) / expérimental (0,15 %). Les garde-fous FTMO de l'EA (stop quotidien 3 %, "
                  "perte max 8 %, plafond de risque portefeuille) sont assurés par le gardien du moteur (profil prop firm).")
    invalidation = "Aucun module n'a d'espérance individuelle positive ; le sélecteur ne fait que les mélanger."
    grid = {"min_score": [70.0, 75.0, 80.0]}
    default = {"min_score": 70.0}

    def generate(self, ctx: Ctx, p: dict, ex: ExitCfg) -> Signals:
        n = ctx.n
        side, stop_k, tp_k, risk, atr_u, score_u = (np.zeros(n, np.int8), np.zeros(n), np.zeros(n), np.ones(n),
                                                    np.full(n, np.nan), np.zeros(n))
        grade = np.full(n, 2, np.int8)
        for fn, sl, tp, core in SS_MODULES.values():           # l'ordre du dict = priorité de l'EA
            s, score, atr = fn(ctx)
            free = (side == 0) & (s != 0) & (score >= float(p["min_score"]))
            side[free] = s[free]; stop_k[free] = sl; tp_k[free] = tp; atr_u[free] = atr[free]; score_u[free] = score[free]
            risk[free] = 1.0 if core else EXP_RISK / CORE_RISK
            grade[free] = 2 if core else 1
        b = _ss_base(ctx)
        side = np.where(b["spr_ok"], side, 0).astype(np.int8)
        c = ctx.c
        stop = c - side * stop_k * atr_u
        target = c + side * tp_k * atr_u
        e = ExitCfg("fixed", rr=2.0, time_stop=0)
        return _build(ctx, self.name, side, stop, e, target=target, level_dist=np.zeros(n), grade=grade,
                      max_per_day=5, min_rr_net=0.0, risk_mult=risk)


LEO_CLASSES = (LeoRangeBreakout, LeoBandito, LeoHappyGold, LeoDoubleCroisement, LeoHybrideSuperTrend, LeoCloudEmaAtr,
               LeoGoldScalping, LeoSSMonday, LeoSSLcrb, LeoSSVolShock, LeoSSLdr, LeoSSIbi, LeoSSEef, LeoSuperSelector)
