"""Cinq stratégies de scalping quantitatif pour l'OR (XAUUSD), règles FIGÉES, événements causaux (barre t = données <= t).

Toutes les durées sont en BARRES et les seuils en multiples d'ATR : le même code s'applique à M1/M5/M15 (seul M15 est évalué tant que M1/M5 ne sont pas exportés).
Fenêtre de liquidité : 07h-17h UTC (Londres + New York). Entrée à la clôture du signal (le moteur exécute à l'ouverture suivante), stop et cible absolus.

  gq_sweep      balayage de liquidité : mèche au-delà du plus haut/bas des `lookback` barres puis clôture de retour dedans -> retournement.
  gq_asia_break cassure du range d'Asie (00-07 UTC) à la clôture avec impulsion (corps >= body_atr x ATR), une fois par jour.
  gq_ema_pull   continuation de tendance (EMA 20>50>200) : repli sur l'EMA20 puis bougie de rejet.
  gq_squeeze    compression de volatilité (ATR/ATR long bas durant `squeeze_bars`) puis cassure impulsive.
  gq_zrev       retour à la moyenne : écart à l'EMA20 >= z x ATR en régime sans tendance (ratio d'efficacité bas), cible = EMA20.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import Event, atr_series

PARAMS = {
    "gq_sweep": {"lookback": 32, "wick_frac": 0.5, "min_range_atr": 0.8, "rr": 2.0, "stop_buf": 0.1, "cooldown": 8},
    "gq_asia_break": {"asia": [0, 7], "end_hour": 12, "body_atr": 0.5, "min_width_atr": 0.5, "max_width_atr": 5.0, "buf": 0.05, "rr": 2.0},
    "gq_ema_pull": {"fast": 20, "mid": 50, "slow": 200, "touch_bars": 3, "close_frac": 0.7, "stop_buf": 0.1, "rr": 2.0, "cooldown": 6},
    "gq_squeeze": {"atr_ratio": 0.75, "long": 100, "squeeze_bars": 6, "break_range_atr": 1.2, "stop_atr": 1.5, "rr": 2.5, "cooldown": 12},
    "gq_zrev": {"ema": 20, "z": 2.2, "er_window": 20, "er_max": 0.25, "stop_atr": 1.2, "min_rr": 1.0, "cooldown": 6},
}
SESSION = (7, 17)


def _in_session(idx: pd.DatetimeIndex) -> np.ndarray:
    return (idx.hour >= SESSION[0]) & (idx.hour < SESSION[1])


def _arrays(df: pd.DataFrame):
    return (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))


def sweep(df: pd.DataFrame, p: dict) -> list[Event]:
    o, h, l, c = _arrays(df); atr = atr_series(df, 14); sess = _in_session(df.index)
    ph = pd.Series(h).shift(1).rolling(p["lookback"]).max().to_numpy(); pl = pd.Series(l).shift(1).rolling(p["lookback"]).min().to_numpy()
    out, last = [], -10**9
    for i in range(len(df)):
        if not sess[i] or not np.isfinite(atr[i]) or not np.isfinite(ph[i]) or i - last < p["cooldown"]:
            continue
        rng = h[i] - l[i]
        if rng < p["min_range_atr"] * atr[i] or rng <= 0:
            continue
        if h[i] > ph[i] and c[i] < ph[i] and (h[i] - max(o[i], c[i])) >= p["wick_frac"] * rng:
            stop = h[i] + p["stop_buf"] * atr[i]; out.append(Event(df.index[i], "bearish", stop, c[i] - p["rr"] * (stop - c[i]), "gq_sweep_short")); last = i
        elif l[i] < pl[i] and c[i] > pl[i] and (min(o[i], c[i]) - l[i]) >= p["wick_frac"] * rng:
            stop = l[i] - p["stop_buf"] * atr[i]; out.append(Event(df.index[i], "bullish", stop, c[i] + p["rr"] * (c[i] - stop), "gq_sweep_long")); last = i
    return out


def asia_break(df: pd.DataFrame, p: dict) -> list[Event]:
    o, h, l, c = _arrays(df); atr = atr_series(df, 14); idx = df.index; day = idx.normalize(); hr = idx.hour
    out = []; cur = None; hi = lo = np.nan; fired = False
    for i in range(len(df)):
        if day[i] != cur:
            cur, hi, lo, fired = day[i], -np.inf, np.inf, False
        if p["asia"][0] <= hr[i] < p["asia"][1]:
            hi, lo = max(hi, h[i]), min(lo, l[i]); continue
        if fired or not (p["asia"][1] <= hr[i] < p["end_hour"]) or not np.isfinite(atr[i]) or hi == -np.inf:
            continue
        width = hi - lo
        if not (p["min_width_atr"] * atr[i] <= width <= p["max_width_atr"] * atr[i]) or abs(c[i] - o[i]) < p["body_atr"] * atr[i]:
            continue
        mid = (hi + lo) / 2.0; buf = p["buf"] * atr[i]
        if c[i] > hi + buf and c[i] > o[i]:
            out.append(Event(idx[i], "bullish", mid, c[i] + p["rr"] * (c[i] - mid), "gq_asia_long")); fired = True
        elif c[i] < lo - buf and c[i] < o[i]:
            out.append(Event(idx[i], "bearish", mid, c[i] - p["rr"] * (mid - c[i]), "gq_asia_short")); fired = True
    return out


def ema_pull(df: pd.DataFrame, p: dict) -> list[Event]:
    o, h, l, c = _arrays(df); atr = atr_series(df, 14); sess = _in_session(df.index); s = pd.Series(c)
    ef, em, es = (s.ewm(span=n, adjust=False).mean().to_numpy() for n in (p["fast"], p["mid"], p["slow"]))
    out, last, tb = [], -10**9, p["touch_bars"]
    for i in range(p["slow"], len(df)):
        if not sess[i] or not np.isfinite(atr[i]) or i - last < p["cooldown"] or h[i] <= l[i]:
            continue
        pos = (c[i] - l[i]) / (h[i] - l[i])
        if ef[i] > em[i] > es[i] and ef[i] > ef[i - 5] and l[i - tb + 1: i + 1].min() <= ef[i] and c[i] > ef[i] and c[i] > o[i] and pos >= p["close_frac"]:
            stop = l[i - tb + 1: i + 1].min() - p["stop_buf"] * atr[i]
            if stop < c[i]:
                out.append(Event(df.index[i], "bullish", stop, c[i] + p["rr"] * (c[i] - stop), "gq_pull_long")); last = i
        elif ef[i] < em[i] < es[i] and ef[i] < ef[i - 5] and h[i - tb + 1: i + 1].max() >= ef[i] and c[i] < ef[i] and c[i] < o[i] and (1 - pos) >= p["close_frac"]:
            stop = h[i - tb + 1: i + 1].max() + p["stop_buf"] * atr[i]
            if stop > c[i]:
                out.append(Event(df.index[i], "bearish", stop, c[i] - p["rr"] * (stop - c[i]), "gq_pull_short")); last = i
    return out


def squeeze(df: pd.DataFrame, p: dict) -> list[Event]:
    o, h, l, c = _arrays(df); atr = atr_series(df, 14); sess = _in_session(df.index)
    atr_l = pd.Series(atr).rolling(p["long"]).mean().to_numpy(); sq = (atr / atr_l) < p["atr_ratio"]; n = p["squeeze_bars"]
    hh = pd.Series(h).shift(1).rolling(n).max().to_numpy(); ll = pd.Series(l).shift(1).rolling(n).min().to_numpy()
    out, last = [], -10**9
    for i in range(p["long"] + n, len(df)):
        if not sess[i] or not np.isfinite(atr[i]) or i - last < p["cooldown"] or not sq[i - n:i].all():
            continue
        if (h[i] - l[i]) < p["break_range_atr"] * atr[i]:
            continue
        if c[i] > hh[i] and c[i] > o[i]:
            stop = c[i] - p["stop_atr"] * atr[i]; out.append(Event(df.index[i], "bullish", stop, c[i] + p["rr"] * (c[i] - stop), "gq_squeeze_long")); last = i
        elif c[i] < ll[i] and c[i] < o[i]:
            stop = c[i] + p["stop_atr"] * atr[i]; out.append(Event(df.index[i], "bearish", stop, c[i] - p["rr"] * (stop - c[i]), "gq_squeeze_short")); last = i
    return out


def zrev(df: pd.DataFrame, p: dict) -> list[Event]:
    o, h, l, c = _arrays(df); atr = atr_series(df, 14); sess = _in_session(df.index); s = pd.Series(c)
    ema = s.ewm(span=p["ema"], adjust=False).mean().to_numpy(); w = p["er_window"]
    er = (s.diff(w).abs() / s.diff().abs().rolling(w).sum()).to_numpy()
    out, last = [], -10**9
    for i in range(max(w, p["ema"]) + 1, len(df)):
        if not sess[i] or not np.isfinite(atr[i]) or not np.isfinite(er[i]) or er[i] > p["er_max"] or i - last < p["cooldown"]:
            continue
        z = (c[i] - ema[i]) / atr[i]
        if z >= p["z"]:
            stop = c[i] + p["stop_atr"] * atr[i]
            if (c[i] - ema[i]) / (stop - c[i]) >= p["min_rr"]:
                out.append(Event(df.index[i], "bearish", stop, ema[i], "gq_zrev_short", {"z": float(z)})); last = i
        elif z <= -p["z"]:
            stop = c[i] - p["stop_atr"] * atr[i]
            if (ema[i] - c[i]) / (c[i] - stop) >= p["min_rr"]:
                out.append(Event(df.index[i], "bullish", stop, ema[i], "gq_zrev_long", {"z": float(z)})); last = i
    return out


GENERATORS = {"gq_sweep": sweep, "gq_asia_break": asia_break, "gq_ema_pull": ema_pull, "gq_squeeze": squeeze, "gq_zrev": zrev}


def events(df: pd.DataFrame, name: str, params: dict | None = None) -> list[Event]:
    return GENERATORS[name](df, {**PARAMS[name], **(params or {})})
