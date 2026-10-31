"""Stratégie 1 du cahier : IBS + RSI(2) avec filtre de tendance MM200, long seulement, sur la SÉANCE CASH reconstruite (indices US 09:30-16:00 NY ; GER40 09:00-17:30 Paris).

Décision à la dernière barre M15 de la séance (clôture 16:00 NY / 17:30 Paris) : le cahier décide 5 minutes avant la clôture ; les barres M15 ne le permettent pas, la clôture de la dernière barre est donc utilisée (approximation DÉCLARÉE, exécution à l'ouverture suivante).
Entrée : clôture > moyenne des `ma_days` (200) dernières clôtures de séance ET (IBS < `ibs_max` (0,20) OU RSI(2) < `rsi_max` (10)) ; jamais le vendredi ; au moins `ma_days` séances d'historique (sinon AUCUN événement).
Stop catastrophe `stop_atr` x ATR(14 séances) sous l'entrée ; cible très éloignée (la sortie normale est la règle ci-dessous).
Sortie (`exit_rule`) : à la première clôture de séance supérieure à la clôture de la séance d'entrée ; sinon au bout de `max_sessions` (3) séances.
Taille : risque de base 0,4 % x ciblage de volatilité (cible / volatilité réalisée 20 séances, plafonné à 1,5) x filtre de fin de mois (x1,25 : dernier jour ouvré du mois et 3 premières séances du mois suivant). La spec fixe risk_per_trade = 0,75 % (plafond) :
le facteur de taille f = 0,4 %/0,75 % x vol x fin de mois est transmis par la confiance (confiance = 0,5 + 0,5 f, plancher de score 0,5) : le risque réel ne dépasse jamais 0,75 %.
Aucune valeur démontrée ici : hypothèse publique à valider en PAPER (>= 60 trades).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import Event
from .sessions import cash_sessions
from .rsi2_reversion import rsi2

PARAMS = {"tz": "America/New_York", "open_min": 570, "last_min": 945, "ma_days": 200, "ibs_max": 0.20, "rsi_max": 10.0, "stop_atr": 2.0, "target_atr": 10.0, "max_sessions": 3,
          "base_risk": 0.004, "cap_risk": 0.0075, "vol_window": 20, "vol_cap": 1.5, "eom_factor": 1.25, "eom_first_days": 3}


def _atr14(ss: list[dict], k: int) -> float:
    tr = []
    for j in range(max(1, k - 13), k + 1):
        tr.append(max(ss[j]["high"] - ss[j]["low"], abs(ss[j]["high"] - ss[j - 1]["close"]), abs(ss[j]["low"] - ss[j - 1]["close"])))
    return float(np.mean(tr)) if len(tr) >= 10 else float("nan")


def _eom_flag(ss: list[dict], k: int, first_days: int) -> bool:
    d = ss[k]["day"]; nxt = d + pd.Timedelta(days=1)
    while nxt.dayofweek >= 5:
        nxt += pd.Timedelta(days=1)
    if nxt.month != d.month:
        return True                                                   # dernier jour ouvré du mois
    n_in_month = 0
    for j in range(k, -1, -1):
        if ss[j]["day"].month != d.month:
            break
        n_in_month += 1
    return n_in_month <= first_days and k - n_in_month >= 0


def size_factor(ss: list[dict], k: int, p: dict) -> tuple[float, float, bool]:
    """(facteur de taille f dans ]0,1], facteur vol, fin de mois) : f = base/cap x vol x fin de mois, borné à 1."""
    closes = np.array([s["close"] for s in ss[: k + 1]]); r = np.diff(np.log(closes)); w = p["vol_window"]
    vf = 1.0
    if len(r) >= w + 60:
        vols = pd.Series(r).rolling(w).std().to_numpy(); cur = vols[-1]; ref = np.nanmedian(vols[-250:])
        if np.isfinite(cur) and cur > 0 and np.isfinite(ref):
            vf = float(min(p["vol_cap"], ref / cur))
    eom = _eom_flag(ss, k, p["eom_first_days"])
    return float(min(1.0, p["base_risk"] / p["cap_risk"] * vf * (p["eom_factor"] if eom else 1.0))), vf, eom


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; ss = cash_sessions(df, p["tz"], p["open_min"], p["last_min"]); c = df["close"].to_numpy(float); out = []
    idx = [k for k, s in enumerate(ss) if s["complete"]]
    closes_all = np.array([s["close"] for s in ss])
    for k in idx:
        if k < p["ma_days"] or ss[k]["day"].dayofweek == 4 or ss[k]["high"] <= ss[k]["low"]:
            continue
        s = ss[k]; px = c[s["last"]]; ma = closes_all[k - p["ma_days"] + 1: k + 1].mean()
        if not px > ma:
            continue
        ibs = (s["close"] - s["low"]) / (s["high"] - s["low"])
        r2 = rsi2(closes_all[max(0, k - 30): k + 1])[-1]
        if not (ibs < p["ibs_max"] or (np.isfinite(r2) and r2 < p["rsi_max"])):
            continue
        atr = _atr14(ss, k)
        if not np.isfinite(atr) or atr <= 0:
            continue
        f, vf, eom = size_factor(ss, k, p)
        out.append(Event(df.index[s["last"]], "bullish", px - p["stop_atr"] * atr, px + p["target_atr"] * atr, "ibs_rsi2_trend",
                         {"ibs": float(ibs), "rsi2": float(r2) if np.isfinite(r2) else None, "size_factor": f, "vol_factor": vf, "eom": bool(eom), "confidence": 0.5 + 0.5 * f}))
    return out


def exit_rule(params: dict | None = None):
    p = {**PARAMS, **(params or {})}
    from .sessions import ny_minutes

    def rule(df: pd.DataFrame, pos) -> str | None:
        hm, _, _ = ny_minutes(df.iloc[-1:], p["tz"])
        if hm[0] != p["last_min"]:
            return None                                                    # seulement à la clôture d'une séance
        tail = df.tail(900); ss = [s for s in cash_sessions(tail, p["tz"], p["open_min"], p["last_min"]) if s["complete"]]
        if len(ss) < 2 or tail.index[ss[-1]["last"]] != df.index[-1]:
            return None
        et = pd.Timestamp(pos.entry_time); prior = [j for j, s in enumerate(ss[:-1]) if tail.index[s["last"]] < et]
        if not prior:
            return None
        entry_session = ss[prior[-1]]; n_after = len(ss) - 1 - prior[-1]
        if ss[-1]["close"] > entry_session["close"]:
            return "ibs_rebond"
        return "ibs_temps" if n_after >= p["max_sessions"] else None
    return rule
