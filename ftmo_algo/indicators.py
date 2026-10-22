"""Indicateurs causaux (numpy/pandas). Aucun n'utilise de donnée future."""
from __future__ import annotations
import numpy as np
import pandas as pd


def ema_arr(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def atr_arr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def adx_arr(h, l, c, n=14):
    up = np.r_[0, np.diff(h)]; dn = -np.r_[0, np.diff(l)]
    pdm = np.where((up > dn) & (up > 0), up, 0.0); mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr_arr(h, l, c, n)
    a = np.where(a == 0, np.nan, a)
    pdi = 100 * pd.Series(pdm).ewm(alpha=1 / n, adjust=False).mean().to_numpy() / a
    mdi = 100 * pd.Series(mdm).ewm(alpha=1 / n, adjust=False).mean().to_numpy() / a
    dx = 100 * np.abs(pdi - mdi) / np.where(pdi + mdi == 0, np.nan, pdi + mdi)
    return np.nan_to_num(pd.Series(dx).ewm(alpha=1 / n, adjust=False).mean().to_numpy())


def rolling_pctile(x, n):
    """Rang percentile de x[i] parmi les n dernières valeurs (incluant i). Causal."""
    s = pd.Series(x)
    return s.rolling(n, min_periods=n // 4).apply(lambda w: (w[:-1] < w[-1]).mean() if len(w) > 1 else .5, raw=True).to_numpy()


def shift(x, k=1, fill=np.nan):
    out = np.full_like(x, fill, dtype="float64")
    if k > 0:
        out[k:] = x[:-k]
    else:
        out[:] = x
    return out
