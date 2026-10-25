"""Combinaison causale de flux de résultats journaliers (en R) de plusieurs stratégies.

Principe honnête : combiner des flux dont l'espérance est ~0 réduit la VARIANCE (diversification), pas l'espérance. Ce module sert donc à mesurer
ce que la diversification apporte réellement, avec des poids qui n'utilisent QUE le passé (aucun réglage sur la période évaluée).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def daily_r(trades, key: str = "exit_time") -> pd.Series:
    """Somme des R (nominaux) par jour de sortie (UTC)."""
    if not trades:
        return pd.Series(dtype=float)
    s = pd.Series([t.r_nominal for t in trades], index=pd.DatetimeIndex([getattr(t, key) for t in trades]).normalize())
    return s.groupby(level=0).sum()


def weights_at(R: pd.DataFrame, t: int, lookback: int, scheme: str, min_obs: int = 30, shrink: float = 0.5) -> np.ndarray:
    """Poids (somme 1) calculés avec les lignes < t uniquement. 'invvol' = parité de risque ; 'tilt' = parité de risque x max(0, t-stat rétréci)."""
    k = R.shape[1]; w0 = np.full(k, 1.0 / k)
    win = R.iloc[max(0, t - lookback):t]
    if len(win) < min_obs:
        return w0
    sd = win.std(ddof=1).to_numpy(); sd = np.where(sd > 0, sd, np.nan)
    iv = np.where(np.isfinite(sd), 1.0 / sd, 0.0)
    if iv.sum() <= 0:
        return w0
    if scheme == "invvol":
        return iv / iv.sum()
    if scheme == "tilt":
        tstat = win.mean().to_numpy() / (sd / np.sqrt(len(win))); tstat = np.nan_to_num(tstat) * (1.0 - shrink)
        raw = iv * np.maximum(tstat, 0.0)
        return raw / raw.sum() if raw.sum() > 0 else iv / iv.sum()
    raise ValueError(scheme)


def combine(R: pd.DataFrame, scheme: str = "invvol", lookback: int = 120, target_vol: float | None = None, vol_window: int = 60, max_scale: float = 3.0) -> pd.Series:
    """R/jour du portefeuille. R : jours x stratégies (0 les jours sans trade). Poids du jour t calculés sur [t-lookback, t[ ; ciblage de vol optionnel (causal, plafonné)."""
    R = R.fillna(0.0); n = len(R); vals = R.to_numpy(); out = np.zeros(n)
    for t in range(n):
        out[t] = float(weights_at(R, t, lookback, scheme) @ vals[t])
    port = pd.Series(out, index=R.index)
    if target_vol:
        vol = port.rolling(vol_window).std().shift(1)                      # volatilité connue AVANT le jour t
        scale = (target_vol / vol).clip(upper=max_scale).fillna(0.0)
        port = port * scale
    return port


def diagnostics(R: pd.DataFrame, port: pd.Series) -> dict:
    R = R.fillna(0.0); x = port.to_numpy(); sd = x.std(ddof=1) if len(x) > 2 else 0.0
    corr = R.corr().to_numpy(); k = R.shape[1]; off = corr[~np.eye(k, dtype=bool)]
    cum = np.cumsum(x); dd = float((np.maximum.accumulate(cum) - cum).max()) if len(x) else 0.0
    ind_vol = R.std(ddof=1).to_numpy()
    return {"days": int(len(x)), "mean_r_day": float(x.mean()) if len(x) else 0.0, "vol_r_day": float(sd), "sharpe_ann": float(x.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0,
            "max_dd_r": dd, "avg_pair_corr": float(np.nanmean(off)) if off.size else 0.0,
            "diversification_ratio": float((ind_vol / k).sum() / sd) if sd > 0 else 0.0}
