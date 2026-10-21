from __future__ import annotations

import numpy as np
import pandas as pd

from ..engine import Signals
from .. import indicators as ind


class Strategy:
    name = "base"
    desc = ""
    params: dict = {}
    grid: dict = {}

    def __init__(self, **kw):
        self.p = {**self.params, **kw}

    def entries(self, df):  # -> (side Series, atr Series)
        raise NotImplementedError

    def signals(self, df: pd.DataFrame) -> Signals:
        side, a = self.entries(df)
        side = side.fillna(0).astype(int).values
        a = a.values
        return Signals(side, a * self.p["sl_atr"], a * self.p["tp_atr"], self.p.get("max_hold", 30))


def _cross_up(a, b):
    return (a > b) & (a.shift() <= b.shift())


class EmaPullback(Strategy):
    name = "ema_pullback"
    desc = "Trend (EMA9/21) + RSI(7) exits extreme while price is on the pullback side of BB mid."
    params = dict(fast=9, slow=21, rsi_n=7, lo=30, hi=70, atr_min=0.0004, sl_atr=1.2, tp_atr=2.0, max_hold=30)
    grid = dict(fast=[5, 9, 13], slow=[21, 34, 55], lo=[20, 25, 30, 35], sl_atr=[0.8, 1.2, 1.6], tp_atr=[1.2, 2.0, 3.0])

    def entries(self, df):
        p = self.p
        c = df.close
        f, s = ind.ema(c, p["fast"]), ind.ema(c, p["slow"])
        r = ind.rsi(c, p["rsi_n"])
        a = ind.atr(df)
        mid = c.rolling(20).mean()
        ok = a / c > p["atr_min"]
        long = (f > s) & (r.shift() <= p["lo"]) & (r > p["lo"]) & (c <= mid) & ok
        short = (f < s) & (r.shift() >= p["hi"]) & (r < p["hi"]) & (c >= mid) & ok
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), df.index), a


class BBReversion(Strategy):
    name = "bb_reversion"
    desc = "Range fade: close beyond 2.2σ band with RSI extreme and low ADX; target = mean."
    params = dict(n=20, k=2.2, adx_max=22, sl_atr=1.5, tp_atr=1.5, max_hold=20)
    grid = dict(n=[14, 20, 30], k=[1.8, 2.2, 2.6], adx_max=[18, 22, 28], sl_atr=[1.0, 1.5, 2.0], tp_atr=[1.0, 1.5, 2.0])

    def entries(self, df):
        p = self.p
        c = df.close
        up, mid, lo = ind.bollinger(c, p["n"], p["k"])
        r = ind.rsi(c, 7)
        ad = ind.adx(df)
        a = ind.atr(df)
        calm = ad < p["adx_max"]
        long = (c < lo) & (r < 25) & calm
        short = (c > up) & (r > 75) & calm
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), df.index), a


class VwapReversion(Strategy):
    name = "vwap_reversion"
    desc = "Fade stretches (z-score) away from rolling VWAP when volume is not exploding."
    params = dict(n=60, z=2.0, vol_max=2.5, sl_atr=1.6, tp_atr=1.4, max_hold=25)
    grid = dict(n=[30, 60, 120], z=[1.6, 2.0, 2.5], sl_atr=[1.2, 1.6, 2.2], tp_atr=[1.0, 1.4, 2.0])

    def entries(self, df):
        p = self.p
        v = ind.rolling_vwap(df, p["n"])
        z = ind.zscore(df.close - v, p["n"])
        vr = df.volume / df.volume.rolling(60).mean()
        a = ind.atr(df)
        long = (z < -p["z"]) & (vr < p["vol_max"])
        short = (z > p["z"]) & (vr < p["vol_max"])
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), df.index), a


class SqueezeBreakout(Strategy):
    name = "squeeze_breakout"
    desc = "Donchian breakout right after a Bollinger-width squeeze (volatility expansion)."
    params = dict(n=20, squeeze_pct=0.25, sl_atr=1.3, tp_atr=3.0, max_hold=40)
    grid = dict(n=[15, 20, 30], squeeze_pct=[0.15, 0.25, 0.35], sl_atr=[1.0, 1.3, 1.8], tp_atr=[2.0, 3.0, 4.0])

    def entries(self, df):
        p = self.p
        c = df.close
        up, mid, lo = ind.bollinger(c, 20, 2)
        width = (up - lo) / mid
        sq = width.rolling(240).rank(pct=True).shift() < p["squeeze_pct"]
        hh = df.high.rolling(p["n"]).max().shift()
        ll = df.low.rolling(p["n"]).min().shift()
        a = ind.atr(df)
        recent = sq.rolling(5).max() > 0
        long = (c > hh) & recent
        short = (c < ll) & recent
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), df.index), a


class MomentumBurst(Strategy):
    name = "momentum_burst"
    desc = "Range-expansion bar on a volume spike, continuation in the bar's direction."
    params = dict(vol_x=2.5, rng_x=1.8, sl_atr=1.0, tp_atr=1.6, max_hold=12)
    grid = dict(vol_x=[2.0, 2.5, 3.5], rng_x=[1.4, 1.8, 2.4], sl_atr=[0.8, 1.0, 1.4], tp_atr=[1.2, 1.6, 2.4])

    def entries(self, df):
        p = self.p
        a = ind.atr(df).shift()
        vr = df.volume / df.volume.rolling(60).mean().shift()
        body = df.close - df.open
        big = (body.abs() > p["rng_x"] * a) & (vr > p["vol_x"])
        strong = (df.close - df.low) / (df.high - df.low).replace(0, np.nan)
        long = big & (body > 0) & (strong > 0.75)
        short = big & (body < 0) & (strong < 0.25)
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), df.index), ind.atr(df)


class LiquiditySweep(Strategy):
    name = "liquidity_sweep"
    desc = "Stop-hunt reversal: wick takes out N-bar high/low, closes back inside with a rejection candle."
    params = dict(n=30, wick=0.55, sl_atr=1.0, tp_atr=2.2, max_hold=25)
    grid = dict(n=[20, 30, 60], wick=[0.45, 0.55, 0.65], sl_atr=[0.8, 1.0, 1.4], tp_atr=[1.6, 2.2, 3.0])

    def entries(self, df):
        p = self.p
        hh = df.high.rolling(p["n"]).max().shift()
        ll = df.low.rolling(p["n"]).min().shift()
        rng = (df.high - df.low).replace(0, np.nan)
        lower = (np.minimum(df.open, df.close) - df.low) / rng
        upper = (df.high - np.maximum(df.open, df.close)) / rng
        long = (df.low < ll) & (df.close > ll) & (lower > p["wick"])
        short = (df.high > hh) & (df.close < hh) & (upper > p["wick"])
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), df.index), ind.atr(df)


class RegimeRouter(Strategy):
    name = "regime_router"
    desc = "Meta-algo: ADX high -> squeeze_breakout/ema_pullback, ADX low -> bb_reversion."
    params = dict(adx_hi=25, adx_lo=18, sl_atr=1.2, tp_atr=2.0, max_hold=30)
    grid = dict(adx_hi=[22, 25, 30], adx_lo=[14, 18, 22])

    def entries(self, df):
        ad = ind.adx(df)
        a = ind.atr(df)
        t, _ = EmaPullback().entries(df)
        r, _ = BBReversion().entries(df)
        side = pd.Series(np.where(ad > self.p["adx_hi"], t, np.where(ad < self.p["adx_lo"], r, 0)), df.index)
        return side, a


class MLDirection(Strategy):
    """Walk-forward logistic model on lagged features; trades when calibrated P is extreme.
    Retrained every `retrain` bars on the trailing window only (no look-ahead; label horizon purged)."""
    name = "ml_direction"
    desc = "Rolling logistic regression on returns/RSI/vol/volume features, trades confident predictions."
    params = dict(train=6000, retrain=1500, horizon=5, thr=0.56, sl_atr=1.2, tp_atr=1.8, max_hold=10)
    grid = dict(thr=[0.54, 0.56, 0.60], horizon=[3, 5, 10], sl_atr=[1.0, 1.2, 1.6], tp_atr=[1.4, 1.8, 2.4])

    def _features(self, df):
        c = df.close
        lr = np.log(c).diff()
        f = pd.DataFrame({
            "r1": lr, "r3": lr.rolling(3).sum(), "r10": lr.rolling(10).sum(), "r30": lr.rolling(30).sum(),
            "rsi": (ind.rsi(c, 7) - 50) / 50, "z": ind.zscore(c, 30),
            "vol": lr.rolling(20).std() / lr.rolling(200).std(), "vr": np.log(df.volume / df.volume.rolling(60).mean()),
        })
        return f.replace([np.inf, -np.inf], np.nan)

    def entries(self, df):
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        p = self.p
        f = self._features(df)
        h = p["horizon"]
        y = (df.close.shift(-h) > df.close).astype(int)
        side = np.zeros(len(df), int)
        X = f.values
        yv = y.values
        for start in range(p["train"], len(df), p["retrain"]):
            lo, hi = start - p["train"], start - h  # purge: labels at t use t+h, so stop at start-h
            tr = slice(lo, hi)
            m = ~np.isnan(X[tr]).any(axis=1)
            if m.sum() < 500:
                continue
            sc = StandardScaler().fit(X[tr][m])
            clf = LogisticRegression(C=0.5, max_iter=200).fit(sc.transform(X[tr][m]), yv[tr][m])
            seg = slice(start, min(start + p["retrain"], len(df)))
            ok = ~np.isnan(X[seg]).any(axis=1)
            prob = np.full(seg.stop - seg.start, 0.5)
            prob[ok] = clf.predict_proba(sc.transform(X[seg][ok]))[:, 1]
            side[seg] = np.where(prob > p["thr"], 1, np.where(prob < 1 - p["thr"], -1, 0))
        return pd.Series(side, df.index), ind.atr(df)


REGISTRY = {c.name: c for c in (EmaPullback, BBReversion, VwapReversion, SqueezeBreakout, MomentumBurst, LiquiditySweep, RegimeRouter, MLDirection)}


def get(name, **kw):
    return REGISTRY[name](**kw)
