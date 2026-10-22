"""Contexte d'un instrument : toutes les séries causales dérivées, calculées UNE fois puis partagées
par tous les algos. Règle : à l'indice i, rien ne dépend de données postérieures à la clôture de i ;
les bougies H1/H4/D1 ne sont lues qu'une fois CLOSES (align_htf)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from ..data.quality import resample_ohlc, align_htf
from ..engine.market import build_market, Market
from ..engine.news import NewsCalendar
from ..indicators import ema_arr, adx_arr
from ..instruments import SPECS, Spec
from ..timeutil import ns

HOUR_NS = 3_600_000_000_000


def _htf_series(m15, tf, offset="0h"):
    h = resample_ohlc(m15, tf, offset)
    return h


class Ctx:
    def __init__(self, sym: str, m15: pd.DataFrame, spec: Spec | None = None, news: NewsCalendar | None = None,
                 fine: pd.DataFrame | None = None):
        self.sym = sym
        self.spec = spec or SPECS[sym]
        self.df = m15
        self.mk: Market = build_market(sym, m15, self.spec, news, fine)
        mk = self.mk
        self.n = mk.n
        o, h, l, c = mk.o, mk.h, mk.l, mk.c
        self.o, self.h, self.l, self.c = o, h, l, c
        self.atr = np.maximum(mk.atr, 1e-12)
        self.ema20, self.ema50, self.ema200 = ema_arr(c, 20), ema_arr(c, 50), ema_arr(c, 200)
        self.adx = adx_arr(h, l, c, 14)
        a_mean = pd.Series(self.atr).rolling(96 * 20, min_periods=96).mean().to_numpy()
        self.vol_ratio = np.nan_to_num(self.atr / a_mean, nan=1.0)
        cl = pd.Series(c)
        sma = cl.rolling(20).mean(); sd = cl.rolling(20).std()
        self.bb_z = ((cl - sma) / sd.replace(0, np.nan)).to_numpy()
        self.bb_bw = (4 * sd / sma).to_numpy()
        # fuseau local de la place principale
        loc = m15.index.tz_convert(self.spec.session_tz or "UTC")
        self.local_min = (loc.hour * 60 + loc.minute).to_numpy()
        self.local_day = (ns(loc.tz_localize(None).normalize()) // 86_400_000_000_000)
        self.utc_hour = m15.index.hour.to_numpy() + m15.index.minute.to_numpy() / 60
        # HTF sans fuite
        offs = "22h" if self.spec.kind in ("fx_usdq", "fx_usdb", "fx_jpy", "metal") else "0h"
        self.h1, self.h4, self.d1 = (_htf_series(m15, "H1"), _htf_series(m15, "H4"), _htf_series(m15, "D1", offs))
        tc = mk.tc
        self.ix1, self.ix4, self.ixd = (align_htf(tc, x) for x in (self.h1, self.h4, self.d1))
        self.h1_trend = self._trend(self.h1, self.ix1, 20, 50)
        self.h4_trend = self._trend(self.h4, self.ix4, 20, 50)
        self.d1_trend = self._trend(self.d1, self.ixd, 10, 30)
        self.h1_adx = self._al(self.ix1, adx_arr(self.h1.high.to_numpy(), self.h1.low.to_numpy(), self.h1.close.to_numpy()))
        self.h1_ema50 = self._al(self.ix1, ema_arr(self.h1.close.to_numpy(), 50))
        self.h1_ema20 = self._al(self.ix1, ema_arr(self.h1.close.to_numpy(), 20))
        dh, dl = self.d1.high.to_numpy(), self.d1.low.to_numpy()
        self.pd_high, self.pd_low = self._al(self.ixd, dh), self._al(self.ixd, dl)
        self.wk_high = self._al(self.ixd, pd.Series(dh).rolling(5).max().to_numpy())
        self.wk_low = self._al(self.ixd, pd.Series(dl).rolling(5).min().to_numpy())
        self._sessions()
        _, _, self.since_news = (mk.news_block, None, None)
        nc = news or NewsCalendar.default(m15.index[0], m15.index[-1])
        self.news = nc
        _, _, self.since_news = nc.masks(mk.t, mk.bar_ns())
        k = np.searchsorted(nc.t, mk.t, side="left")
        nxt = np.where(k < len(nc.t), nc.t[np.minimum(k, max(len(nc.t) - 1, 0))] if len(nc.t) else 0, 0)
        self.until_news = np.where(k < len(nc.t), (nxt - mk.t) / 6e10, 1e9) if len(nc.t) else np.full(self.n, 1e9)

    # ------------------------------------------------------------------
    def _trend(self, htf, ix, f, s):
        cl = htf.close.to_numpy()
        e1, e2 = ema_arr(cl, f), ema_arr(cl, s)
        t = np.where((cl > e1) & (e1 > e2), 1, np.where((cl < e1) & (e1 < e2), -1, 0))
        return self._al(ix, t.astype("float64"), fill=0.0)

    @staticmethod
    def _al(ix, arr, fill=np.nan):
        out = np.full(len(ix), fill, dtype="float64")
        ok = ix >= 0
        out[ok] = np.asarray(arr, dtype="float64")[ix[ok]]
        return out

    def _sessions(self):
        """Extrêmes de la séance asiatique (00-07 UTC) une fois terminée, et de la séance en cours."""
        df = pd.DataFrame({"h": self.h, "l": self.l, "day": self.local_day, "hr": self.utc_hour})
        asia = df["hr"] < 7
        ah = df["h"].where(asia); al = df["l"].where(asia)
        g = df["day"]
        self.asia_high = ah.groupby(g).cummax().groupby(g).ffill().to_numpy()
        self.asia_low = al.groupby(g).cummin().groupby(g).ffill().to_numpy()
        done = df["hr"] >= 7  # utilisable seulement quand la séance asiatique est close
        self.asia_high = np.where(done, self.asia_high, np.nan)
        self.asia_low = np.where(done, self.asia_low, np.nan)
        self.day_hi_sofar = df["h"].groupby(g).cummax().shift(1).where(g.eq(g.shift(1))).to_numpy()
        self.day_lo_sofar = df["l"].groupby(g).cummin().shift(1).where(g.eq(g.shift(1))).to_numpy()

    def sessions_vwap_z(self):
        """z-score du prix vs VWAP ancré à l'ouverture locale (volume tick), causal."""
        if hasattr(self, "_vz"):
            return self._vz
        tp = (self.h + self.l + self.c) / 3
        v = np.maximum(self.df["volume"].to_numpy("float64"), 1.0)
        anchor = self.local_day
        s = pd.DataFrame({"pv": tp * v, "v": v, "p2v": tp * tp * v, "g": anchor})
        cpv, cv, cp2 = (s.groupby("g")[k].cumsum() for k in ("pv", "v", "p2v"))
        vw = cpv / cv
        var = (cp2 / cv - vw ** 2).clip(lower=1e-12)
        self._vz = ((self.c - vw) / np.sqrt(var)).to_numpy()
        self._vw = vw.to_numpy()
        return self._vz

    # ------------------------------------------------------------------
    def features(self, side: np.ndarray, stop: np.ndarray, level_dist_atr=None) -> np.ndarray:
        """Features communes (n, k) pour le filtre ML. Toutes causales."""
        ang = 2 * np.pi * self.utc_hour / 24
        rd = np.abs(self.c - np.nan_to_num(stop, nan=self.c.mean())) / self.atr
        ld = np.zeros(self.n) if level_dist_atr is None else np.nan_to_num(level_dist_atr, nan=3.0)
        f = np.column_stack([self.atr / self.c * 1e4, self.vol_ratio, self.h1_adx, self.adx,
                             self.h1_trend * side, self.h4_trend * side, self.d1_trend * side,
                             np.sin(ang), np.cos(ang), ld, rd, self.bb_z * side,
                             np.minimum(self.since_news, 600) / 60.0]).astype("float32")
        return np.nan_to_num(f)

    FEAT_NAMES = ("atr_bps", "vol_ratio", "h1_adx", "adx", "h1_align", "h4_align", "d1_align", "sin_h", "cos_h",
                  "dist_level_atr", "stop_atr", "bbz_side", "since_news_h")
