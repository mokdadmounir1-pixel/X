"""Batterie d'hypothèses documentées, évaluées en rendements JOURNALIERS nets de coûts.

Chaque hypothèse a des paramètres FIXÉS a priori (aucun balayage : un balayage multiplierait les essais).
Toutes sont causales : le signal d'un jour n'utilise que des prix connus avant l'entrée.
Les heures de séance sont en heure de New York (les timestamps UTC reconstruits tiennent compte du DST).

Hypothèses (références) :
  intraday_momentum : le rendement (clôture veille -> 10:00 NY) prédit celui de la dernière demi-heure (Gao et al., 2018).
  overnight_drift   : long de 16:00 NY à 09:30 NY le lendemain (prime nocturne des indices actions).
  tsmom_20 / tsmom_60 : momentum de série temporelle journalier (Moskowitz, Ooi, Pedersen, 2012).
  reversal_1d       : retour à la moyenne à 1 jour (Jegadeesh 1990, Lehmann 1990).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

TZ = "America/New_York"
SLOTS = {"0930": (9, 30), "1000": (10, 0), "1530": (15, 30), "1600": (16, 0)}


def session_prices(df: pd.DataFrame, tz: str = TZ, bar_minutes: int = 15, slots: tuple = tuple(SLOTS)) -> pd.DataFrame:
    """Prix à l'heure locale T, un jour par ligne (index = date locale).

    prix(T) = ouverture de la barre qui COMMENCE à T ; à défaut, clôture de la barre qui commence 15 min avant T
    (robuste aux pauses de séance : la barre de 16:00 n'existe pas tous les jours chez ce courtier).
    """
    idx = df.index.tz_localize("UTC").tz_convert(tz)
    hm = np.asarray(idx.hour * 60 + idx.minute)
    dates = pd.DatetimeIndex(idx.date)
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    cols = {}
    for name in slots:
        h, m = SLOTS[name]
        t = h * 60 + m
        s_open = pd.Series(o[hm == t], index=dates[hm == t])
        s_close = pd.Series(c[hm == t - bar_minutes], index=dates[hm == t - bar_minutes])
        s_open = s_open[~s_open.index.duplicated(keep="last")]
        s_close = s_close[~s_close.index.duplicated(keep="last")]
        cols[name] = s_open.combine_first(s_close)
    return pd.DataFrame(cols).sort_index()


@dataclass
class Result:
    net: pd.Series      # rendement net par jour (fraction du notionnel), indexé par date d'ENTRÉE
    gross: pd.Series
    bh: pd.Series       # buy & hold sur la même fenêtre (benchmark pour l'alpha)
    n_trades: int


def _pos_cost(pos: pd.Series, cost_rt: float) -> pd.Series:
    """Coût d'une variation de position : |Δpos| x demi-coût aller-retour (pos 0 en début et en fin)."""
    d = pos.diff().abs().fillna(pos.abs())
    return d * cost_rt / 2.0


def intraday_momentum(p: pd.DataFrame, cost_rt: float, **_) -> Result:
    prev_close = p["1600"].shift(1)
    r_first = p["1000"] / prev_close - 1.0
    pos = np.sign(r_first)
    gross = pos * (p["1600"] / p["1530"] - 1.0)
    trade = pos.abs()
    net = gross - trade * cost_rt
    bh = p["1600"] / p["1600"].shift(1) - 1.0  # rendement du MÊME jour (benchmark du test d'alpha)
    ok = net.dropna()
    return Result(ok, gross.reindex(ok.index), bh.reindex(ok.index), int(trade.reindex(ok.index).sum()))


def overnight_drift(p: pd.DataFrame, cost_rt: float, swap: float = 0.0, **_) -> Result:
    gross = p["0930"].shift(-1) / p["1600"] - 1.0
    net = gross - cost_rt - swap
    bh = p["1600"].shift(-1) / p["1600"] - 1.0  # buy & hold close-à-close sur la même fenêtre d'entrée
    ok = net.dropna()
    return Result(ok, gross.reindex(ok.index), bh.reindex(ok.index), len(ok))


def _daily_strategy(p: pd.DataFrame, cost_rt: float, sig: pd.Series) -> Result:
    close = p["1600"].dropna()
    ret_next = close.shift(-1) / close - 1.0
    pos = sig.reindex(close.index).fillna(0.0)
    gross = pos * ret_next
    net = (gross - _pos_cost(pos, cost_rt)).iloc[:-1]
    ok = net.dropna()
    return Result(ok, gross.reindex(ok.index), ret_next.reindex(ok.index), int(pos.diff().abs().fillna(pos.abs()).sum() // 2))


def tsmom(p: pd.DataFrame, cost_rt: float, lookback: int = 20, **_) -> Result:
    close = p["1600"].dropna()
    return _daily_strategy(p, cost_rt, np.sign(close / close.shift(lookback) - 1.0))


def reversal_1d(p: pd.DataFrame, cost_rt: float, **_) -> Result:
    close = p["1600"].dropna()
    return _daily_strategy(p, cost_rt, -np.sign(close / close.shift(1) - 1.0))


HYPOTHESES: dict[str, Callable[..., Result]] = {
    "intraday_momentum": intraday_momentum,
    "overnight_drift": overnight_drift,
    "tsmom_20": lambda p, c, **k: tsmom(p, c, lookback=20),
    "tsmom_60": lambda p, c, **k: tsmom(p, c, lookback=60),
    "reversal_1d": reversal_1d,
}


# --- statistiques ---------------------------------------------------------------------------------------------
def newey_west_t(x, lag: int = 5) -> float:
    """t-stat de la moyenne, variance robuste à l'autocorrélation (Bartlett)."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 10 or x.std() == 0:
        return 0.0
    e = x - x.mean()
    var = float(e @ e) / n
    for k in range(1, min(lag, n - 1) + 1):
        var += 2 * (1 - k / (lag + 1)) * float(e[k:] @ e[:-k]) / n
    return float(x.mean() / np.sqrt(max(var, 1e-18) / n))


def alpha_vs_benchmark(y, bench, lag: int = 5) -> dict:
    """MCO y = a + b*bench ; t(a) robuste. Un alpha non significatif = simple exposition au marché (bêta)."""
    y, b = np.asarray(y, float), np.asarray(bench, float)
    m = np.isfinite(y) & np.isfinite(b)
    y, b = y[m], b[m]
    n = y.size
    if n < 20 or b.std() == 0:
        return {"alpha": float(y.mean()) if n else 0.0, "beta": 0.0, "t_alpha": newey_west_t(y, lag)}
    X = np.column_stack([np.ones(n), b])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ coef
    XtX_inv = np.linalg.inv(X.T @ X)
    S = (X * res[:, None]).T @ (X * res[:, None])
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        G = (X[k:] * res[k:, None]).T @ (X[:-k] * res[:-k, None])
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    return {"alpha": float(coef[0]), "beta": float(coef[1]), "t_alpha": float(coef[0] / np.sqrt(max(cov[0, 0], 1e-24)))}


def summarize(net: pd.Series, bh: pd.Series) -> dict:
    x = net.to_numpy()
    sd = x.std(ddof=1) if x.size > 1 else 0.0
    half = x.size // 2
    eq = np.cumprod(1.0 + x) if x.size else np.array([1.0])
    dd = float((1 - eq / np.maximum.accumulate(eq)).max()) if x.size else 0.0
    return {"n_days": int(x.size), "mean_bps": float(x.mean() * 1e4) if x.size else 0.0,
            "sharpe_annual": float(x.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0,
            "t_nw": newey_west_t(x), "hit_rate": float((x > 0).mean()) if x.size else 0.0,
            "mean_first_half_bps": float(x[:half].mean() * 1e4) if half else 0.0,
            "mean_second_half_bps": float(x[half:].mean() * 1e4) if x.size - half else 0.0,
            "max_drawdown_unit": dd, **{f"bh_{k}": v for k, v in alpha_vs_benchmark(x, bh.to_numpy()).items()}}
