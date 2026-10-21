"""Contexte M1 d'un instrument : séries causales partagées par les algos scalp (rien ne dépend du futur)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from ..engine.market import build_market, Market
from ..engine.news import NewsCalendar
from ..indicators import atr_arr
from ..instruments import SPECS, Spec, value_per_unit
from ..timeutil import ns

WARMUP = 300


class ScalpCtx:
    def __init__(self, sym: str, m1: pd.DataFrame, spec: Spec | None = None, news: NewsCalendar | None = None):
        self.sym = sym
        self.spec = spec or SPECS[sym]
        self.df = m1
        # coûts majorés ×3 pendant 90 minutes autour des annonces (même durée qu'en M15, indépendante de la barre)
        self.mk: Market = build_market(sym, m1, self.spec, news, None, cost_window_min=90)
        mk = self.mk
        self.n = mk.n
        self.o, self.h, self.l, self.c = mk.o, mk.h, mk.l, mk.c
        self.atr = np.maximum(atr_arr(self.h, self.l, self.c, 30), 1e-12)
        self.atr_prev = np.r_[self.atr[0], self.atr[:-1]]          # ATR hors barre courante
        self.vol = np.maximum(m1["volume"].to_numpy("float64"), 1.0) if "volume" in m1 else np.ones(self.n)
        self.vol_med = pd.Series(self.vol).rolling(60, min_periods=20).median().shift(1).to_numpy()
        loc = m1.index.tz_convert(self.spec.session_tz or "UTC")
        self.local_min = (loc.hour * 60 + loc.minute).to_numpy()
        self.local_day = ns(loc.tz_localize(None).normalize()) // 86_400_000_000_000
        self.utc_hour = m1.index.hour.to_numpy() + m1.index.minute.to_numpy() / 60
        so = self.spec.session_open
        self.since_open = self.local_min - (so[0] * 60 + so[1])       # minutes depuis l'ouverture de la séance principale
        self.liquid = self._liquid()
        # coût aller-retour attendu (unités de prix) connu à la clôture de la barre i : spread courant + 2 slippages + commission
        value = value_per_unit(self.spec, float(np.nanmedian(self.c)))
        self.rt_cost = mk.spr + 2 * self.spec.slippage + self.spec.commission_lot / value
        self._vz = None

    def _liquid(self) -> np.ndarray:
        """Fenêtres liquides FIXES (non optimisées) : 3 h après l'ouverture de la place principale ; FX/or/crypto : Londres
        07-11 UTC et ouverture New York 12:30-16:30 UTC."""
        if self.spec.kind == "index":
            return (self.since_open >= 0) & (self.since_open < 180)
        h = self.utc_hour
        return ((h >= 7) & (h < 11)) | ((h >= 12.5) & (h < 16.5))

    def vwap_z(self):
        """z-score du prix vs VWAP ancré à l'ouverture de la séance principale (volume tick), causal."""
        if self._vz is not None:
            return self._vz, self._vw
        tp = (self.h + self.l + self.c) / 3
        w = np.where(self.since_open >= 0, self.vol, 0.0)
        s = pd.DataFrame({"pv": tp * w, "v": w, "p2v": tp * tp * w, "g": self.local_day})
        cpv, cv, cp2 = (s.groupby("g")[k].cumsum() for k in ("pv", "v", "p2v"))
        cv = cv.replace(0, np.nan)
        vw = cpv / cv
        var = (cp2 / cv - vw ** 2).clip(lower=1e-18)
        self._vz = ((self.c - vw) / np.sqrt(var)).to_numpy()
        self._vw = vw.to_numpy()
        return self._vz, self._vw
