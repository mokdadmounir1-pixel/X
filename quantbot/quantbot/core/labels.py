"""Labels : résultat NET (en R nominal) du trade standard si on avait pris chaque côté à chaque barre.

Reproduit, barre par barre, la sémantique de `core.sim.TradingEngine` (signal à la clôture de t, fill à l'ouverture
de t+1, niveaux calculés depuis close[t], stop prioritaire, gap à l'ouverture, max_hold, fermeture de week-end,
trous de données, coûts spread/slippage/commission, plafond de levier). Un test vérifie l'identité avec le moteur.

Attention : un label regarde jusqu'à `max_hold_bars` barres dans le futur. Toute coupure train/validation doit
purger au moins cette durée de chaque côté (`purge_bars`).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import Settings
from ..indicators.core import atr_np
from ..risk.calendar import in_weekend_blackout


@dataclass
class Labels:
    long_r: np.ndarray   # NaN = pas de trade possible à cette barre
    short_r: np.ndarray
    seg_start: np.ndarray

    def purge_bars(self, settings: Settings) -> int:
        return settings.backtest.max_hold_bars + 2


def _floored_atr_series(h, l, c, period: int, floor_frac: float) -> np.ndarray:
    atr = atr_np(h, l, c, period)
    if floor_frac <= 0:
        return atr
    med = pd.Series(atr).rolling(200, min_periods=1).median().to_numpy()
    return np.where(np.isfinite(med), np.maximum(atr, floor_frac * med), atr)


def _segments(index: pd.DatetimeIndex, max_gap_hours: float):
    ns = index.values.astype("datetime64[ns]").astype("int64")  # indépendant de la résolution (pandas 3)
    gap_h = np.concatenate(([0.0], np.diff(ns) / 3.6e12))
    seg = np.zeros(len(index), dtype=np.int64)
    start = 0
    for i in range(1, len(index)):
        if gap_h[i] > max_gap_hours:
            start = i
        seg[i] = start
    return gap_h, seg


def compute_labels(df: pd.DataFrame, settings: Settings) -> Labels:
    s, r, ex, bt = settings, settings.risk, settings.execution, settings.backtest
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    n = len(df)
    atr = _floored_atr_series(h, l, c, s.detection.atr_period, s.signals.atr_floor_frac)
    gap_h, seg = _segments(df.index, bt.max_gap_hours)
    weekend = np.zeros(n, dtype=bool)
    if r.flat_before_weekend:
        weekend = np.array([in_weekend_blackout(t, r.session_tz, r.weekend_cutoff_hour) for t in df.index])
    sl = ex.slippage + ex.spread / 2.0   # même formule que PaperBroker
    fee = ex.fee_rate
    out = {1: np.full(n, np.nan), -1: np.full(n, np.nan)}
    for t in range(n - 1):
        if (t + 1) - seg[t] <= bt.warmup_bars or weekend[t] or weekend[t + 1] or gap_h[t + 1] > bt.max_gap_hours:
            continue
        a = atr[t]
        if not np.isfinite(a) or a <= 0:
            continue
        dist = r.atr_stop_mult * a
        ref = c[t]
        for side in (1, -1):
            stop = ref - side * dist
            if stop <= 0:
                continue
            tp = ref + side * r.reward_risk * dist
            fill = o[t + 1] * (1 + side * sl)
            ex_px, market = None, True
            for j in range(t + 1, n):
                if j > t + 1 and gap_h[j] > bt.max_gap_hours:
                    ex_px, market = c[j - 1], True
                    break
                oj, hj, lj, cj = o[j], h[j], l[j], c[j]
                held = j - (t + 1)
                if side == 1:
                    if oj <= stop:
                        ex_px = oj
                    elif lj <= stop:
                        ex_px = stop
                    elif hj >= tp:
                        ex_px, market = tp, False
                else:
                    if oj >= stop:
                        ex_px = oj
                    elif hj >= stop:
                        ex_px = stop
                    elif lj <= tp:
                        ex_px, market = tp, False
                if ex_px is None and held >= bt.max_hold_bars:
                    ex_px = cj
                if ex_px is None and weekend[j]:
                    ex_px = cj
                if ex_px is not None:
                    break
            if ex_px is None:  # fin des données : le moteur clôture à la dernière clôture ; on n'invente pas
                continue
            exit_eff = ex_px * (1 - side * sl) if market else ex_px
            per_unit = side * (exit_eff - fill) - fee * (fill + exit_eff)
            scale = min(1.0 / dist, r.max_leverage / (r.risk_per_trade * ref))
            out[side][t] = per_unit * scale
    return Labels(out[1], out[-1], seg)
