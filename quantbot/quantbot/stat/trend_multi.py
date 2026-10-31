"""Stratégie 3 du cahier : suivi de tendance multi-actifs (compte financé), signal trimestriel/annuel/mensuel, risque égal par marché, rebalancement hebdomadaire.

Signal d'un marché = moyenne des votes de 3 horizons (21, 63, 252 jours) : +1 si le rendement de l'horizon est positif, -1 sinon (valeurs -1, -1/3, +1/3, +1).
Position (en fraction de l'équité, signée) = signal x risque_quotidien_cible / volatilité des rendements quotidiens sur 60 jours (risque égal par marché), plafonnée par marché (`max_pos`) et au total (`max_gross`).
Rebalancement au dernier jour de négociation de chaque semaine (clôture) ; la position s'applique aux rendements des jours SUIVANTS (aucune fuite). Pas de take profit ; stop de sécurité `stop_atr` x ATR(14) depuis l'entrée de la période : touché, le marché reste à plat jusqu'au rebalancement suivant.
Coûts : |variation de position| x (spread/2 + commission + slippage) par marché. Les SWAPS quotidiens du courtier sont NON CONNUS : ils sont exclus et déclarés comme tels (le cahier demande de les intégrer : à faire quand ils sont relevés).
Outil de recherche : le backtest consomme UN essai ; aucune valeur démontrée.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (21, 63, 252)
PARAMS = {"horizons": list(HORIZONS), "vol_window": 60, "daily_risk": 0.00125, "max_pos": 3.0, "max_gross": 6.0, "stop_atr": 4.0, "atr_period": 14}


def daily_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Barres journalières UTC (open, high, low, close) depuis des barres intrajournalières ; le jour en cours incomplet n'est pas exclu ici (l'appelant coupe)."""
    g = df.groupby(df.index.normalize())
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last()})


def momentum_signal(close: pd.Series, horizons=HORIZONS) -> pd.Series:
    """Moyenne des votes de signe des rendements sur chaque horizon ; NaN tant que l'horizon le plus long n'est pas disponible."""
    votes = [np.sign(close / close.shift(h) - 1.0) for h in horizons]
    sig = sum(votes) / len(votes)
    sig[close.shift(max(horizons)).isna()] = np.nan
    return sig


def week_ends(index: pd.DatetimeIndex) -> pd.Series:
    """Vrai au dernier jour de négociation de chaque semaine ISO présent dans l'index."""
    wk = index.isocalendar(); key = (wk["year"].astype(int) * 100 + wk["week"].astype(int)).to_numpy()
    last = np.r_[key[1:] != key[:-1], False]                       # la dernière semaine, incomplète, n'est jamais rebalancée
    return pd.Series(last, index=index)


def atr(d: pd.DataFrame, n: int = 14) -> pd.Series:
    tr = pd.concat([d["high"] - d["low"], (d["high"] - d["close"].shift()).abs(), (d["low"] - d["close"].shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def target_positions(daily: dict[str, pd.DataFrame], params: dict | None = None) -> pd.DataFrame:
    """Positions-cibles calculées à la clôture de chaque jour (utilisables seulement le jour suivant), non plafonnées par le portefeuille."""
    p = {**PARAMS, **(params or {})}; out = {}
    for k, d in daily.items():
        r = np.log(d["close"]).diff(); vol = r.rolling(p["vol_window"]).std()
        pos = momentum_signal(d["close"], p["horizons"]) * p["daily_risk"] / vol
        out[k] = pos.clip(-p["max_pos"], p["max_pos"])
    return pd.DataFrame(out)


def simulate(daily: dict[str, pd.DataFrame], costs: dict[str, float], params: dict | None = None) -> dict:
    """Simulation jour par jour. `costs[k]` = coût par unité de variation de position (demi-spread + commission + slippage, en fraction du prix)."""
    p = {**PARAMS, **(params or {})}; keys = list(daily); idx = sorted(set().union(*[d.index for d in daily.values()]))
    idx = pd.DatetimeIndex(idx); close = pd.DataFrame({k: daily[k]["close"] for k in keys}).reindex(idx); lo = pd.DataFrame({k: daily[k]["low"] for k in keys}).reindex(idx); hi = pd.DataFrame({k: daily[k]["high"] for k in keys}).reindex(idx)
    tgt = target_positions(daily, p).reindex(idx); atrs = pd.DataFrame({k: atr(daily[k], p["atr_period"]) for k in keys}).reindex(idx); wend = week_ends(idx)
    pos = pd.DataFrame(0.0, index=idx, columns=keys); entry = {k: np.nan for k in keys}; flat_until_reb = {k: False for k in keys}; ret = pd.Series(0.0, index=idx); cost_paid = pd.Series(0.0, index=idx)
    cur = {k: 0.0 for k in keys}; contrib = {k: 0.0 for k in keys}
    for t in range(1, len(idx)):
        day = idx[t]; day_ret = 0.0; turnover_cost = 0.0
        for k in keys:                                                       # rendement du jour sur la position tenue depuis la veille
            c0, c1 = close[k].iloc[t - 1], close[k].iloc[t]
            if cur[k] != 0.0 and np.isfinite(c0) and np.isfinite(c1) and c0 > 0:
                px_exit = c1; a = atrs[k].iloc[t - 1]
                if np.isfinite(entry[k]) and np.isfinite(a):                  # stop de sécurité sur les extrêmes du jour
                    s = entry[k] - p["stop_atr"] * a if cur[k] > 0 else entry[k] + p["stop_atr"] * a
                    if (cur[k] > 0 and lo[k].iloc[t] <= s) or (cur[k] < 0 and hi[k].iloc[t] >= s):
                        px_exit = s; flat_until_reb[k] = True
                gain = cur[k] * (px_exit / c0 - 1.0); contrib[k] += gain; day_ret += gain
                if flat_until_reb[k]:
                    turnover_cost += abs(cur[k]) * costs.get(k, 0.0); cur[k] = 0.0; entry[k] = np.nan
        if wend.iloc[t]:                                                     # rebalancement à la clôture : effet dès le jour suivant
            new = {k: (0.0 if not np.isfinite(tgt[k].iloc[t]) else float(tgt[k].iloc[t])) for k in keys}
            gross = sum(abs(v) for v in new.values())
            if gross > p["max_gross"]:
                new = {k: v * p["max_gross"] / gross for k, v in new.items()}
            for k in keys:
                turnover_cost += abs(new[k] - cur[k]) * costs.get(k, 0.0)
                if new[k] != cur[k]:
                    entry[k] = close[k].iloc[t] if new[k] != 0.0 else np.nan
                cur[k] = new[k]; flat_until_reb[k] = False
        ret.iloc[t] = day_ret - turnover_cost; cost_paid.iloc[t] = turnover_cost
        for k in keys:
            pos.iloc[t, pos.columns.get_loc(k)] = cur[k]
    return {"returns": ret, "positions": pos, "costs_paid": cost_paid, "contribution": contrib}


def metrics(ret: pd.Series, ppy: float = 252.0) -> dict:
    r = ret.dropna(); r = r[r.index >= r[r != 0].index[0]] if (r != 0).any() else r
    if len(r) < 20 or r.std() == 0:
        return {"n_days": int(len(r)), "ann_return": None, "ann_vol": None, "sharpe": None, "max_drawdown": None}
    eq = (1 + r).cumprod(); dd = float((eq / eq.cummax() - 1).min())
    return {"n_days": int(len(r)), "ann_return": float(eq.iloc[-1] ** (ppy / len(r)) - 1), "ann_vol": float(r.std() * np.sqrt(ppy)), "sharpe": float(r.mean() / r.std() * np.sqrt(ppy)), "max_drawdown": dd}


def basket_buy_hold(daily: dict[str, pd.DataFrame], params: dict | None = None) -> pd.Series:
    """Comparateur obligatoire : panier long seulement au même risque égal (signal = +1, même taille, même rebalancement, sans coûts) ; mesure le bêta du panier."""
    p = {**PARAMS, **(params or {})}; d2 = {k: d for k, d in daily.items()}
    long_only = {}
    for k, d in d2.items():
        r = np.log(d["close"]).diff(); vol = r.rolling(p["vol_window"]).std(); long_only[k] = (p["daily_risk"] / vol).clip(0, p["max_pos"])
    pos = pd.DataFrame(long_only); idx = pos.index; close = pd.DataFrame({k: d["close"] for k, d in d2.items()}).reindex(idx); wend = week_ends(idx)
    cur = pd.Series(0.0, index=pos.columns); out = pd.Series(0.0, index=idx)
    for t in range(1, len(idx)):
        rr = (close.iloc[t] / close.iloc[t - 1] - 1.0).fillna(0.0); out.iloc[t] = float((cur * rr).sum())
        if wend.iloc[t]:
            cur = pos.iloc[t].fillna(0.0); g = cur.abs().sum(); cur = cur * (p["max_gross"] / g) if g > p["max_gross"] else cur
    return out
