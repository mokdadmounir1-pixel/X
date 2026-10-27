"""IL-SVR — Institutional Liquidity Sweep & VWAP Reversion, pour INDICES (barres M15 ; M1/M5 dès qu'elles seront exportées).

Fenêtres UTC : 08h00-10h30 (Europe) et 13h30-16h00 (ouverture de Wall Street), jamais ailleurs. Setup continu (aucun booléen) : moyenne géométrique de
  B  épuisement : le prix touche/dépasse la bande ±k sigma du VWAP du jour (poids = volume de ticks) ;
  Sw balayage + retour : dépassement du plus haut/bas de la PREMIÈRE HEURE de la fenêtre puis clôture de retour à l'intérieur ;
  D  divergence de flux (proxy) : le CVD (volume de ticks x position de clôture dans la barre) ne confirme pas le nouvel extrême ;
  V  régime : pas d'expansion de volatilité (ATR / ATR long).
Sortie : cible = VWAP central ; stop = au-delà de l'extrême balayé ; rapport minimum `min_rr`. LIMITES HONNÊTES : le vrai CVD exige des transactions/ticks classés (proxy par barre ici) ; la sortie en deux temps
(50 % au VWAP, 50 % à la bande opposée) n'existe pas dans le moteur unique : une seule cible, le VWAP ; la divergence inter-indices (ES/NQ) n'est pas modélisée ; Hawkes est remplacé par le ratio d'ATR.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .apex import ramp
from .events import Event, atr_series

PARAMS = {"windows": [[8.0, 10.5], [13.5, 16.0]], "first_hour_bars": 4, "vwap_from_hour": 7.0, "band_k": 2.0, "min_bars": 8, "omega_min": 0.35, "stop_buf_atr": 0.1, "min_rr": 2.0, "cooldown": 6,
          "cvd_lookback": 16, "vol_lo": 1.4, "vol_hi": 2.2, "atr_long": 100}


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close")); v = df["volume"].to_numpy(float)
    atr = atr_series(df, 14); atr_l = pd.Series(atr).rolling(p["atr_long"]).mean().to_numpy(); V = 1.0 - ramp(atr / atr_l, p["vol_lo"], p["vol_hi"])
    hrs = df.index.hour + df.index.minute / 60.0; day = df.index.normalize(); rng_ = np.where(h > l, h - l, np.nan)
    delta = v * (2 * (c - l) / rng_ - 1.0); delta = np.nan_to_num(delta)
    out, last = [], -10**9; cur = None; sw = swp = swp2 = 0.0; n = 0; cvd = 0.0; cvd_hist: list[float] = []; fh: dict = {}
    for i in range(len(df)):
        if day[i] != cur:
            cur, sw, swp, swp2, n, cvd, cvd_hist, fh = day[i], 0.0, 0.0, 0.0, 0, 0.0, [], {}
        if hrs[i] < p["vwap_from_hour"]:
            continue
        tp = (h[i] + l[i] + c[i]) / 3.0; w = max(v[i], 1e-9); sw += w; swp += w * tp; swp2 += w * tp * tp; n += 1; cvd += delta[i]; cvd_hist.append(cvd)
        win = next((k for k, (a, b) in enumerate(p["windows"]) if a <= hrs[i] < b), None)
        if win is None:
            continue
        a0 = p["windows"][win][0]; fhk = (win,)
        if fhk not in fh and hrs[i] >= a0:
            fh[fhk] = {"bars": [], "hi": -np.inf, "lo": np.inf}
        f = fh[fhk]
        if len(f["bars"]) < p["first_hour_bars"]:                  # première heure de la fenêtre : on construit la plage, aucun signal
            f["bars"].append(i); f["hi"], f["lo"] = max(f["hi"], h[i]), min(f["lo"], l[i]); continue
        if n < p["min_bars"] or not np.isfinite(atr[i]) or i - last < p["cooldown"]:
            continue
        vwap = swp / sw; sd = np.sqrt(max(swp2 / sw - vwap ** 2, 0.0))
        if sd <= 0:
            continue
        lb = cvd_hist[-p["cvd_lookback"] - 1:-1]; scale = (np.std(delta[max(0, i - 50):i + 1]) * 4.0) + 1e-9
        # vente : balayage haut
        B = float(ramp((h[i] - (vwap + p["band_k"] * sd)) / sd, -0.3, 0.2)); Sw = float(ramp((h[i] - f["hi"]) / atr[i], 0.0, 0.3) * ramp((f["hi"] - c[i]) / atr[i], 0.0, 0.3))
        D = float(ramp((max(lb) - cvd) / scale, 0.0, 1.0)) if lb else 0.0; om_s = (B * Sw * D * V[i]) ** 0.25
        B2 = float(ramp(((vwap - p["band_k"] * sd) - l[i]) / sd, -0.3, 0.2)); Sw2 = float(ramp((f["lo"] - l[i]) / atr[i], 0.0, 0.3) * ramp((c[i] - f["lo"]) / atr[i], 0.0, 0.3))
        D2 = float(ramp((cvd - min(lb)) / scale, 0.0, 1.0)) if lb else 0.0; om_b = (B2 * Sw2 * D2 * V[i]) ** 0.25
        if om_s >= p["omega_min"] and om_s > om_b:
            stop = h[i] + p["stop_buf_atr"] * atr[i]; risk = stop - c[i]
            if risk > 0 and (c[i] - vwap) / risk >= p["min_rr"]:
                out.append(Event(df.index[i], "bearish", stop, vwap, "ilsvr_short", {"confidence": min(om_s, 1.0), "omega": float(om_s), "B": B, "Sw": Sw, "D": D, "V": float(V[i])})); last = i
        elif om_b >= p["omega_min"] and om_b > om_s:
            stop = l[i] - p["stop_buf_atr"] * atr[i]; risk = c[i] - stop
            if risk > 0 and (vwap - c[i]) / risk >= p["min_rr"]:
                out.append(Event(df.index[i], "bullish", stop, vwap, "ilsvr_long", {"confidence": min(om_b, 1.0), "omega": float(om_b), "B": B2, "Sw": Sw2, "D": D2, "V": float(V[i])})); last = i
    return out
