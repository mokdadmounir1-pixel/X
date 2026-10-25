"""SMC_OB_FVG — Order Block + Fair Value Gap en confluence, règles FIGÉES, détection MATRICIELLE et causale.

Sur les barres HTF TERMINÉES (H1 ou H4 ; groupes New York, jamais de fuite) :
  1. DÉPLACEMENT (b1) : corps >= body_atr x ATR(HTF), clôture dans le haut (>= clv) ou le bas (<= 1-clv) de la bougie, volume >= vol_mult x moyenne
     mobile des vol_n barres PRÉCÉDENTES (filtre de volume), et cassure de structure (clôture au-delà du plus haut/bas des bos_n barres précédentes).
  2. ORDER BLOCK (b0) : la bougie juste avant le déplacement, de couleur OPPOSÉE (baissière pour un achat). Zone OB = [low, high] de b0.
  3. FAIR VALUE GAP : écart entre b0 et la bougie suivante b2 (haussier : low[b2] > high[b0] ; baissier : high[b2] < low[b0]) d'au moins gap_atr x ATR.
  Toutes ces conditions sont des masques calculés d'un coup sur les tableaux de prix (aucune boucle sur les motifs), puis révélés barre par barre.
  4. FILTRE DE TENDANCE : tendance D1 terminée alignée (bias="1D") ou aucun (bias="none").
Zone d'entrée = Consequent Encroachment (50 %) du FVG. Déclenchement quand une barre de BASE (M15) touche le CE sans clôturer au-delà du bord lointain de l'OB.
Stop = bord lointain de l'OB -/+ buf x ATR(HTF). CIBLE = le premier pivot structurel confirmé (swing_n barres de chaque côté, sur target_lookback barres HTF) donnant au moins min_rr x le risque,
plafonnée à max_rr x le risque ; SANS pivot qualifiant le setup est IGNORÉ : peu de trades, mais seulement ceux à fort rapport gain/risque.
Entrée MARCHÉ à l'ouverture suivante (aucun avantage de fill supposé). Une zone invalidée par une clôture HTF au-delà de son bord lointain, expirée (`expiry` barres) ou déjà déclenchée ne sert plus.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..data.mtf import group_keys, htf_state
from .events import Event

PARAMS = {"body_atr": 1.2, "clv": 0.70, "vol_mult": 1.2, "gap_atr": 0.25, "bos_n": 10, "swing_n": 2, "target_lookback": 80,
          "min_rr": 3.0, "max_rr": 8.0, "buf": 0.2, "expiry": 24, "atr_period": 14, "vol_n": 20, "bias": "1D"}


def htf_arrays(df: pd.DataFrame, rule: str) -> dict:
    """Barres HTF agrégées par reduceat (tableaux) + index de base auquel chaque groupe est TERMINÉ (début du groupe suivant)."""
    gid = group_keys(df.index, rule)
    starts = np.flatnonzero(np.r_[True, gid[1:] != gid[:-1]])
    ends = np.r_[starts[1:], len(df)]
    o, h, l, c, w = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    return {"o": o[starts], "h": np.maximum.reduceat(h, starts), "l": np.minimum.reduceat(l, starts), "c": c[ends - 1], "v": np.add.reduceat(w, starts),
            "start_idx": starts, "done_at": np.r_[starts[1:], -1], "t": df.index[starts]}


def wilder_atr(h, l, c, n: int) -> np.ndarray:
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    out = np.full(len(tr), np.nan)
    if len(tr) >= n:
        out[n - 1] = tr[:n].mean()
        for i in range(n, len(tr)):
            out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def _rolling_prev_mean(x: np.ndarray, n: int) -> np.ndarray:
    """Moyenne des n valeurs PRÉCÉDENTES (la valeur courante exclue) : causal."""
    cs = np.cumsum(np.r_[0.0, x])
    out = np.full(len(x), np.nan)
    if len(x) > n:
        out[n:] = (cs[n:len(x)] - cs[:len(x) - n]) / n
    return out


def _prev_extreme(x: np.ndarray, n: int, fn) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for j in range(n, len(x)):
        out[j] = fn(x[j - n:j])
    return out


def setup_masks(a: dict, p: dict) -> dict:
    """Masques booléens par indice i = b2 (3e bougie) : setup haussier / baissier complet + niveaux. Tout est calculé matriciellement, en n'utilisant que des barres <= i."""
    o, h, l, c, v = a["o"], a["h"], a["l"], a["c"], a["v"]
    n = len(o)
    atr = wilder_atr(h, l, c, p["atr_period"])
    vol_ma = _rolling_prev_mean(v, p["vol_n"])
    hi_prev = _prev_extreme(h, p["bos_n"], np.max)
    lo_prev = _prev_extreme(l, p["bos_n"], np.min)
    rng = np.maximum(h - l, 1e-12)
    clv = (c - l) / rng
    body = c - o
    disp_up = (body >= p["body_atr"] * atr) & (clv >= p["clv"]) & (v >= p["vol_mult"] * vol_ma) & (c > hi_prev)
    disp_dn = (-body >= p["body_atr"] * atr) & (clv <= 1 - p["clv"]) & (v >= p["vol_mult"] * vol_ma) & (c < lo_prev)
    bull = np.zeros(n, bool); bear = np.zeros(n, bool)
    ob_lo = np.full(n, np.nan); ob_hi = np.full(n, np.nan); fvg_lo = np.full(n, np.nan); fvg_hi = np.full(n, np.nan); atr1 = np.full(n, np.nan)
    if n >= 3:
        i = np.arange(2, n)
        b0, b1 = i - 2, i - 1
        gap_up = l[i] - h[b0]
        gap_dn = l[b0] - h[i]
        with np.errstate(invalid="ignore"):
            ok_up = disp_up[b1] & (o[b0] > c[b0]) & (gap_up >= p["gap_atr"] * atr[b1])
            ok_dn = disp_dn[b1] & (o[b0] < c[b0]) & (gap_dn >= p["gap_atr"] * atr[b1])
        bull[i], bear[i] = ok_up, ok_dn
        ob_lo[i], ob_hi[i] = l[b0], h[b0]
        fvg_lo[i] = np.where(ok_up, h[b0], h[i]); fvg_hi[i] = np.where(ok_up, l[i], l[b0])      # haussier : [high b0, low b2] ; baissier : [high b2, low b0]
        atr1[i] = atr[b1]
    bull[:3] = False; bear[:3] = False     # le 1er groupe peut être partiel : on l'écarte
    return {"bull": bull, "bear": bear, "ob_lo": ob_lo, "ob_hi": ob_hi, "fvg_lo": fvg_lo, "fvg_hi": fvg_hi, "atr": atr1, "atr_all": atr}


def swing_target(a: dict, k: int, direction: str, entry: float, risk: float, p: dict) -> Optional[float]:
    """Premier pivot structurel CONFIRMÉ (à k) au-delà de l'entrée donnant >= min_rr x risque ; plafonné à max_rr x risque ; None si aucun."""
    m = p["swing_n"]
    lo_j = max(m, k - p["target_lookback"]); hi_j = k - m
    if hi_j < lo_j:
        return None
    arr = a["h"] if direction == "bullish" else a["l"]
    js = np.arange(lo_j, hi_j + 1)
    cmp = (lambda x, y: x > y) if direction == "bullish" else (lambda x, y: x < y)
    piv = np.ones(len(js), bool)
    for d in range(1, m + 1):
        piv &= cmp(arr[js], arr[js - d]) & ~cmp(arr[js + d], arr[js])
    levels = arr[js][piv]
    if direction == "bullish":
        cand = np.sort(levels[levels > entry]); need = entry + p["min_rr"] * risk
        good = cand[cand >= need]
        return float(min(good[0], entry + p["max_rr"] * risk)) if len(good) else None
    cand = np.sort(levels[levels < entry])[::-1]; need = entry - p["min_rr"] * risk
    good = cand[cand <= need]
    return float(max(good[0], entry - p["max_rr"] * risk)) if len(good) else None


def _run(df: pd.DataFrame, rule: str, p: dict, want_zones: bool):
    a = htf_arrays(df, rule)
    m = setup_masks(a, p)
    bias_s = htf_state(df, "1D").to_numpy() if p.get("bias", "1D") == "1D" else None
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    gid_pos = np.searchsorted(a["start_idx"], np.arange(len(df)), side="right") - 1      # groupe de chaque barre de base
    events: list[Event] = []; zones: list[dict] = []; active: list[dict] = []
    k_done = -1
    for i in range(len(df)):
        g = gid_pos[i]
        while k_done < g - 1:                                       # le groupe k_done+1 est TERMINÉ dès qu'une barre du groupe suivant apparaît
            k_done += 1
            k = k_done
            hc = a["c"][k]
            for z in list(active):                                  # invalidation par clôture HTF au-delà du bord lointain, expiration
                if (z["dir"] == "bullish" and hc < z["far"]) or (z["dir"] == "bearish" and hc > z["far"]) or k - z["born"] > p["expiry"]:
                    z["end"] = df.index[i]; z["why"] = "expirée" if k - z["born"] > p["expiry"] else "invalidée"; active.remove(z)
            for d, mk in (("bullish", m["bull"]), ("bearish", m["bear"])):
                if k < len(mk) and mk[k]:
                    lo, hi = (m["fvg_lo"][k], m["fvg_hi"][k]) if d == "bullish" else (m["fvg_lo"][k], m["fvg_hi"][k])
                    top, bot = max(lo, hi), min(lo, hi)
                    z = {"dir": d, "born": k, "ob_lo": float(m["ob_lo"][k]), "ob_hi": float(m["ob_hi"][k]), "fvg_lo": float(bot), "fvg_hi": float(top),
                         "ce": float((top + bot) / 2), "atr": float(m["atr"][k]), "t0": a["t"][k - 2], "t_created": df.index[i], "used": False, "end": None, "why": None,
                         "far": float(m["ob_lo"][k] if d == "bullish" else m["ob_hi"][k])}
                    z["stop"] = z["far"] - p["buf"] * z["atr"] if d == "bullish" else z["far"] + p["buf"] * z["atr"]
                    active.append(z)
                    if want_zones:
                        zones.append(z)
        for z in reversed(active):
            if z["used"]:
                continue
            if bias_s is not None and bias_s[i] != (1 if z["dir"] == "bullish" else -1):
                continue
            k = g - 1
            if z["dir"] == "bullish" and l[i] <= z["ce"] and c[i] >= z["far"]:
                risk = c[i] - z["stop"]
                tgt = swing_target(a, k, "bullish", float(c[i]), float(risk), p) if risk > 0 else None
                z["used"] = True; z["end"] = df.index[i]; z["why"] = "déclenchée" if tgt else "ignorée (R:R < %.1f)" % p["min_rr"]
                if tgt:
                    events.append(Event(df.index[i], "bullish", z["stop"], tgt, f"smc_long_{rule}", {"ce": z["ce"], "ob": (z["ob_lo"], z["ob_hi"]), "rr": (tgt - c[i]) / risk}))
                    break
            elif z["dir"] == "bearish" and h[i] >= z["ce"] and c[i] <= z["far"]:
                risk = z["stop"] - c[i]
                tgt = swing_target(a, k, "bearish", float(c[i]), float(risk), p) if risk > 0 else None
                z["used"] = True; z["end"] = df.index[i]; z["why"] = "déclenchée" if tgt else "ignorée (R:R < %.1f)" % p["min_rr"]
                if tgt:
                    events.append(Event(df.index[i], "bearish", z["stop"], tgt, f"smc_short_{rule}", {"ce": z["ce"], "ob": (z["ob_lo"], z["ob_hi"]), "rr": (c[i] - tgt) / risk}))
                    break
        active = [z for z in active if not z["used"]]
    return events, zones


def events(df: pd.DataFrame, rule: str, p: dict = PARAMS) -> list[Event]:
    return _run(df, rule, {**PARAMS, **p}, False)[0]


def zones(df: pd.DataFrame, rule: str, p: dict = PARAMS) -> list[dict]:
    """Zones OB/FVG détectées avec leur cycle de vie (pour les graphiques) : dir, ob_lo/ob_hi, fvg_lo/fvg_hi, ce, stop, t0, t_created, end, why."""
    return _run(df, rule, {**PARAMS, **p}, True)[1]
