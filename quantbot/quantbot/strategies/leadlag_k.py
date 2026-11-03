"""S2 LEADLAG-K : l'actif rattrape avec retard ce que ses « drivers » ont déjà fait ; on trade l'écart entre le mouvement attendu (régression de Kalman à bêtas en marche aléatoire) et le mouvement réalisé.

XAUUSD : drivers DXY (-dDXY) et USDJPY (dUSDJPY) ; US10Y / ZN du cahier ABSENTS chez ce courtier (non collectés) : AUCUN taux réel n'est inventé. GER40 : driver US500.
Chaque jour (UTC) : décalage l* = argmax |corr(r^X_t, z_{t-l})| sur la VEILLE (estimation sur barres M1 alignées) et LLR = SOMME_{l>0} corr^2 / SOMME_{l<0} corr^2 ; jour ignoré si l* < 1 ou LLR <= `llr_min` (le driver doit MENER).
En ligne : b_t en marche aléatoire (Kalman), prédiction faite AVANT de voir r^X_t ; gap_t = SOMME_{s=t-L+1..t} (b_s' z_{s-l*}) - SOMME r^X_s ; z(gap) sur `z_window` barres précédentes.
Entrée : |z(gap)| >= `z_in` (2) ET |gap| >= `spread_mult` (3) x spread (en rendement) ; sens = signe(gap) (gap > 0 : X est en retard sur le haut). Sortie : |z| < `z_out` (0,3) (`exit_rule`) ou temps (`max_hold_bars` de la spec, plafond 2 l*).
Données M1 requises (X et drivers dans data/live) ; sinon AUCUN événement. Barres M1 alignées au lieu de ticks asynchrones : l'estimateur de Hayashi-Yoshida (stat/leadlag.py) est testé mais l'estimation du jour utilise les barres alignées (déclaré). Aucune valeur démontrée.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..stat.leadlag import KalmanBetas, lag_by_bars
from .events import Event
from .external_data import load_bars

PARAMS = {"drivers": ["DXY", "USDJPY"], "root": None, "lag_max": 5, "llr_min": 1.0, "L": 5, "z_window": 240, "z_in": 2.0, "z_out": 0.3, "spread_mult": 3.0, "stop_mult": 4.0, "q": 1e-8, "r": 1e-8, "cooldown": 3}
_CACHE: dict = {}


def _aligned(df: pd.DataFrame, p: dict):
    zs = []
    for s in p["drivers"]:
        b = load_bars(s, "M1", p["root"])
        if b is None:
            return None
        zs.append(np.log(b["close"]).reindex(df.index, method="ffill", limit=5))
    return pd.concat(zs, axis=1).diff()


def features(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame | None:
    """gap, z(gap), l* du jour, spread en rendement ; None si un driver manque. Causal (calibration de la veille, prédiction avant observation)."""
    p = {**PARAMS, **(params or {})}; Z = _aligned(df, p)
    if Z is None:
        return None
    r = np.log(df["close"]).diff().to_numpy(float); Zv = Z.to_numpy(float); n = len(df); day = df.index.normalize(); gap = np.full(n, np.nan); lag_day = np.zeros(n, int)
    days = pd.unique(day); kal = None; yhat = np.full(n, np.nan)
    for di, d in enumerate(days):
        idx = np.flatnonzero(day == d)
        if di == 0:
            continue
        prev = np.flatnonzero(day == days[di - 1]); a, b = r[prev], Zv[prev, 0]; ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < 200:
            continue
        ll = lag_by_bars(a[ok], b[ok], p["lag_max"]); l = ll["lag_star"]
        if l < 1 or not (ll["llr"] > p["llr_min"]):
            continue
        kal = KalmanBetas(Zv.shape[1], p["q"], p["r"]); lag_day[idx] = l
        for t in idx:
            if t - l < 1:
                continue
            z = Zv[t - l]
            if not (np.isfinite(r[t]) and np.isfinite(z).all()):
                continue
            yhat[t] = kal.predict(z); kal.update(z, r[t])
    L = p["L"]; ys = pd.Series(yhat); rs = pd.Series(r); g = ys.rolling(L).sum() - rs.rolling(L).sum(); gap = g.to_numpy()
    zs = (g - g.shift(1).rolling(p["z_window"], min_periods=60).mean()) / g.shift(1).rolling(p["z_window"], min_periods=60).std()
    spread = (df["spread"] / df["close"]).to_numpy(float) if "spread" in df else np.zeros(n)
    return pd.DataFrame({"gap": gap, "z": zs.to_numpy(), "lag": lag_day, "spread_ret": spread}, index=df.index)


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; F = features(df, p)
    if F is None:
        return []
    _CACHE["key"] = (df.index[-1], len(df)); _CACHE["feat"] = F
    c = df["close"].to_numpy(float); out = []; last = -10**9
    ok = (F["z"].abs() >= p["z_in"]) & (F["gap"].abs() >= p["spread_mult"] * F["spread_ret"]) & (F["lag"] >= 1)
    for i in np.flatnonzero(ok.to_numpy()):
        if i - last < p["cooldown"]:
            continue
        d = 1 if F["gap"].iloc[i] > 0 else -1; last = i; move = max(abs(F["gap"].iloc[i]), 3 * F["spread_ret"].iloc[i]) * c[i]
        out.append(Event(df.index[i], "bullish" if d > 0 else "bearish", float(c[i] - d * p["stop_mult"] * move), float(c[i] + d * move), "leadlag_k", {"z": float(F["z"].iloc[i]), "gap": float(F["gap"].iloc[i]), "lag": int(F["lag"].iloc[i])}))
    return out


def exit_rule(params: dict | None = None):
    p = {**PARAMS, **(params or {})}

    def rule(df: pd.DataFrame, pos) -> str | None:
        F = _CACHE.get("feat") if _CACHE.get("key") == (df.index[-1], len(df)) else None
        if F is None:
            F = features(df.tail(3000), p)
        if F is None or not np.isfinite(F["z"].iloc[-1]):
            return None
        held = int((df.index > pd.Timestamp(pos.entry_time)).sum()); l = int(F["lag"].iloc[-1])
        if abs(F["z"].iloc[-1]) < p["z_out"]:
            return "leadlag_rattrapage"
        return "leadlag_2l" if l >= 1 and held >= 2 * l else None
    return rule
