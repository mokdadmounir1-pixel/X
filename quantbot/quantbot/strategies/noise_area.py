"""Stratégie 2 du cahier : Noise Area (bandes de bruit intrajournalières), indices US, séance cash NY. Adaptation DÉCLARÉE : barres M15 au lieu de M1 (les décisions ont lieu aux demi-heures, donc le prix à 10:00, 10:30... est la clôture de la barre M15 qui finit à cette heure).

Bandes : pour chaque instant t de la séance, sigma(t) = moyenne sur les 14 séances précédentes de |prix(t) - ouverture du jour| / ouverture du jour. Bande haute = max(ouverture, clôture de la veille) x (1 + sigma) ; basse = min(...) x (1 - sigma).
Décision aux demi-heures 10:00 -> 15:30 NY (barres qui commencent à 09:45, 10:15, ..., 15:15) : clôture au-dessus de la bande haute ET au-dessus du VWAP du jour -> achat ; sous la bande basse ET sous le VWAP -> vente ; un seul trade par séance.
Stop initial = max(bande haute, VWAP) (long) / min(bande basse, VWAP) (short) ; sortie (`exit_rule`) aux demi-heures suivantes si la clôture repasse ce niveau (recalculé), et à la dernière barre de la séance (fermeture forcée). Jamais de position la nuit.
Risque 0,25 % du compte (spec) ; refus si coût > `risk.max_cost_r` (test de coûts). VWAP = prix typique pondéré par les ticks (volume du courtier). Le test de coûts sur 10 ans de M1 avec le vrai spread FTMO du cahier N'EST PAS faisable ici (données absentes) : PAPER seulement.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .events import Event
from .sessions import cash_sessions, ny_minutes

PARAMS = {"tz": "America/New_York", "open_min": 570, "last_min": 945, "lookback": 14, "decision_minutes": [585 + 30 * i for i in range(12)], "target_mult": 8.0}


def _day_arrays(df: pd.DataFrame, s: dict, tz: str):
    sub = df.iloc[s["first"]: s["last"] + 1]; hm, _, _ = ny_minutes(sub, tz)
    return sub, np.asarray(hm)


def sigma_by_minute(df: pd.DataFrame, ss: list[dict], k: int, p: dict) -> dict:
    """sigma(minute-de-barre) = moyenne des |clôture(minute) - ouverture| / ouverture sur les `lookback` séances COMPLÈTES précédant k ; NaN s'il en manque."""
    prev = [s for s in ss[:k] if s["complete"]][-p["lookback"]:]
    if len(prev) < p["lookback"]:
        return {}
    acc: dict = {}
    for s in prev:
        sub, hm = _day_arrays(df, s, p["tz"]); o = sub["open"].iloc[0]; cl = sub["close"].to_numpy(float)
        for m, x in zip(hm, cl):
            acc.setdefault(int(m), []).append(abs(x - o) / o)
    return {m: float(np.mean(v)) for m, v in acc.items() if len(v) == p["lookback"]}


def levels(df: pd.DataFrame, ss: list[dict], k: int, i: int, sig: dict, p: dict):
    """(bande haute, bande basse, VWAP) à la barre i de la séance k, ou None."""
    s = ss[k]; sub, hm = _day_arrays(df, s, p["tz"]); j = i - s["first"]
    if k < 1 or not ss[k - 1]["complete"] or int(hm[j]) not in sig:
        return None
    o = float(sub["open"].iloc[0]); pc = ss[k - 1]["close"]; sg = sig[int(hm[j])]
    typ = ((sub["high"] + sub["low"] + sub["close"]) / 3.0).to_numpy(float)[: j + 1]; v = sub["volume"].to_numpy(float)[: j + 1]
    vwap = float((typ * v).sum() / v.sum()) if v.sum() > 0 else float(typ.mean())
    return max(o, pc) * (1 + sg), min(o, pc) * (1 - sg), vwap


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; ss = cash_sessions(df, p["tz"], p["open_min"], p["last_min"]); c = df["close"].to_numpy(float); out = []
    dec = set(int(x) for x in p["decision_minutes"])
    for k in range(p["lookback"] + 1, len(ss)):
        sig = sigma_by_minute(df, ss, k, p)
        if not sig:
            continue
        s = ss[k]; sub, hm = _day_arrays(df, s, p["tz"])
        for j in range(len(sub)):
            if int(hm[j]) not in dec:
                continue
            i = s["first"] + j; L = levels(df, ss, k, i, sig, p)
            if L is None:
                continue
            ub, lb, vw = L; px = c[i]
            if px > ub and px > vw:
                stop = max(ub, vw); out.append(Event(df.index[i], "bullish", stop, px + p["target_mult"] * (px - stop), "noise_area", {"ub": ub, "vwap": vw})); break
            if px < lb and px < vw:
                stop = min(lb, vw); out.append(Event(df.index[i], "bearish", stop, px - p["target_mult"] * (stop - px), "noise_area", {"lb": lb, "vwap": vw})); break
    return out


def exit_rule(params: dict | None = None):
    p = {**PARAMS, **(params or {})}; dec = set(int(x) for x in p["decision_minutes"])

    def rule(df: pd.DataFrame, pos) -> str | None:
        hm, _, _ = ny_minutes(df.iloc[-1:], p["tz"]); m = int(hm[0])
        if m not in dec and m != p["last_min"]:
            return None
        if m == p["last_min"]:
            return "noise_cloture"                                         # fermeture forcée en fin de séance
        tail = df.tail(1800); ss = cash_sessions(tail, p["tz"], p["open_min"], p["last_min"])
        if len(ss) < p["lookback"] + 2 or ss[-1]["last"] != len(tail) - 1:
            return None
        k = len(ss) - 1; sig = sigma_by_minute(tail, ss, k, p); L = levels(tail, ss, k, len(tail) - 1, sig, p) if sig else None
        if L is None:
            return None
        ub, lb, vw = L; px = float(tail["close"].iloc[-1])
        if pos.side == "long":
            return "noise_stop_suiveur" if px < max(ub, vw) else None
        return "noise_stop_suiveur" if px > min(lb, vw) else None
    return rule
