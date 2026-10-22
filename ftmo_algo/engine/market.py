"""Préparation des tableaux numpy d'un instrument (barre de base, ex. M15) pour le moteur."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from ..instruments import Spec
from ..timeutil import ns
from ..indicators import atr_arr
from .news import NewsCalendar

HOUR = 3_600_000_000_000


@dataclass
class Market:
    sym: str
    spec: Spec
    df: pd.DataFrame
    n: int
    t: np.ndarray      # ouverture (ns UTC)
    tc: np.ndarray     # clôture
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    spr: np.ndarray    # spread en unités de prix, par barre
    atr: np.ndarray
    swing_lo: np.ndarray
    swing_hi: np.ndarray
    news_block: np.ndarray
    news_mult: np.ndarray
    pday: np.ndarray   # jour calendaire Prague (entier)
    roll: np.ndarray   # nuits de swap facturées en entrant dans la barre i
    gap_next: np.ndarray  # True si la barre est la dernière avant une fermeture longue
    news_block_next: np.ndarray = None  # blocage d'annonce pour l'OUVERTURE de la barre suivante (connu à la clôture)
    fine: dict | None = None   # données plus fines pour résoudre stop/cible dans la même barre

    def bar_ns(self) -> int:
        return int(np.median(np.diff(self.t))) if self.n > 2 else 900_000_000_000


def build_market(sym: str, df: pd.DataFrame, spec: Spec, news: NewsCalendar | None = None,
                 fine: pd.DataFrame | None = None, struct_n: int = 8) -> Market:
    t = ns(df.index)
    bar = int(np.median(np.diff(t)))
    o, h, l, c = (df[k].to_numpy("float64") for k in ("open", "high", "low", "close"))
    if "spread" in df.columns and np.isfinite(df["spread"]).any():
        spr = np.nan_to_num(df["spread"].to_numpy("float64"), nan=spec.spread)
        spr = np.maximum(spr, spec.spread * 0.5)
    else:
        hr = df.index.hour.to_numpy()
        spr = spec.spread * np.where((hr >= 21) | (hr < 1), 3.0, 1.0)
    a = atr_arr(h, l, c, 14)
    s = pd.Series(l).rolling(struct_n, min_periods=1).min().to_numpy()
    sh = pd.Series(h).rolling(struct_n, min_periods=1).max().to_numpy()
    if news is None:
        news = NewsCalendar.default(df.index[0], df.index[-1])
    nb, nm, _ = news.masks(t, bar)
    nbn, _, _ = news.masks(t + bar, bar)
    local = df.index.tz_convert("Europe/Prague")
    pday = (local.normalize().tz_localize(None).asi8 // 86_400_000_000_000) if hasattr(local, "asi8") else None
    pday = ns(local.tz_localize(None).normalize()) // 86_400_000_000_000
    # nuits de swap : instants 22:00 UTC
    kk = (t - 22 * HOUR) // (24 * HOUR)
    wd = ((np.arange(kk.min() - 1, kk.max() + 2) + 3) % 7)  # jour 0 = 1970-01-01 jeudi (3)
    if spec.kind == "crypto":
        w = np.ones(len(wd))
    elif spec.kind == "index":
        w = np.where(wd == 4, 3.0, np.where(wd >= 5, 0.0, 1.0))
    else:
        w = np.where(wd == 2, 3.0, np.where(wd >= 4, 0.0, 1.0))
    cum = np.cumsum(w)
    base = kk.min() - 1
    roll = np.r_[0.0, cum[kk[1:] - base] - cum[kk[:-1] - base]]
    # dernière barre avant la fermeture du week-end : déterminée par l'HORAIRE (causal, identique en live)
    if spec.kind == "crypto":
        gap = np.zeros(len(t), bool)
    else:
        cl = pd.DatetimeIndex(t + bar, tz="UTC") if False else pd.to_datetime(t + bar, utc=True)
        gap = np.asarray((cl.weekday == 4) & (cl.hour * 60 + cl.minute >= 22 * 60 - 5))
    return Market(sym, spec, df, len(df), t, t + bar, o, h, l, c, spr, a, s, sh, nb, nm, pday, roll, gap,
                  news_block_next=nbn, fine=_fine_index(fine) if fine is not None else None)


def _fine_index(fine: pd.DataFrame) -> dict:
    return {"t": ns(fine.index), "h": fine["high"].to_numpy("float64"), "l": fine["low"].to_numpy("float64"),
            "o": fine["open"].to_numpy("float64"), "c": fine["close"].to_numpy("float64")}
