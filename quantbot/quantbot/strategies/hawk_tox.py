"""S1 HAWK-TOX : flux endogène (Hawkes proche de la criticité) ET flux toxique (VPIN élevé) ET déséquilibre d'intensité marqué, sur XAUUSD (puis US500 quand ses ticks seront collectés).

Entrée (clôture d'une barre M1, tous les seuils figés par la spec) : rho >= `rho_in` (0,8) ET VPIN > quantile `q` (90 %) glissant de ses `q_window` valeurs précédentes ET |I| >= `imb_min` (0,35), I = (lambda_b - lambda_s)/(lambda_b + lambda_s) ; sens = signe(I).
Stop `stop_atr` (1,5) x ATR(14) M1 ; sortie temporelle 30 barres (`max_hold_bars` de la spec) ; sortie anticipée si rho < `rho_out` (0,6) (`exit_rule`).
Événements du processus : variations du mid des TICKS RÉELS classées par la règle du tick (achat/vente). Intensités mises à jour en ligne en O(1) par tick (`OnlineHawkes`).
Écarts DÉCLARÉS avec le cahier : (1) calibration MLE refaite toutes les `refit_minutes` (60) sur les `fit_hours` (6) d'événements PRÉCÉDENTS (causal) au lieu d'une seule calibration « la veille » : sinon rho serait constant dans la journée et « rho repasse sous 0,6 » n'aurait aucun sens ; (2) VPIN sur barres de TEMPS M1 (50 barres), pas des seaux de volume égal ; volume = ticks du courtier.
Sans ticks (data/live/ticks) : AUCUN événement. Aucun backtest historique possible tant que les ticks n'ont pas été collectés ; PAPER avant-coup seulement. Aucune valeur démontrée.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..stat.hawkes import OnlineHawkes, fit_hawkes, tick_rule, vpin_series
from .events import Event, atr_series
from .external_data import load_ticks

PARAMS = {"symbol": "XAUUSD", "root": None, "rho_in": 0.8, "rho_out": 0.6, "imb_min": 0.35, "q": 0.90, "q_window": 1000, "vpin_window": 50, "stop_atr": 1.5, "target_atr": 6.0,
          "refit_minutes": 60, "fit_hours": 6.0, "fit_max_events": 5000, "min_fit_events": 400, "cooldown": 5}
_CACHE: dict = {}


def tick_events(ticks: pd.DataFrame):
    """(t en secondes, type 0 achat / 1 vente) des variations du mid, règle du tick."""
    mid = ticks["mid"].to_numpy(float); s = tick_rule(mid); t = (ticks.index.astype("datetime64[ns]").astype("int64") / 1e9)[1:]; keep = (np.diff(mid) != 0) & (s != 0)
    return t[keep], np.where(s[keep] > 0, 0, 1)


def features(df: pd.DataFrame, params: dict | None = None, ticks: pd.DataFrame | None = None) -> pd.DataFrame | None:
    """rho, vpin, seuil VPIN, imbalance I à la CLÔTURE de chaque barre M1 de `df` ; None sans ticks. Causal : un événement postérieur à la clôture n'est jamais lu."""
    p = {**PARAMS, **(params or {})}; ticks = ticks if ticks is not None else load_ticks(p["symbol"], p["root"])
    if ticks is None or len(ticks) < 1000:
        return None
    t_ev, typ = tick_events(ticks); step = df.index.to_series().diff().median(); step_s = (step.total_seconds() if pd.notna(step) else 60.0)
    t_open = df.index.astype("datetime64[ns]").astype("int64") / 1e9; t_close = t_open + step_s; n = len(df)
    rho = np.full(n, np.nan); imb = np.full(n, np.nan); params_now = None; hawk = None; last_fit = -1e18; e = 0
    for k in range(n):
        tc = t_close[k]
        if tc - last_fit >= p["refit_minutes"] * 60:               # recalibrage sur les événements PRÉCÉDENTS seulement
            lo = np.searchsorted(t_ev, tc - p["fit_hours"] * 3600); hi = np.searchsorted(t_ev, tc, side="left")
            if hi - lo >= p["min_fit_events"]:
                try:
                    f = fit_hawkes(t_ev[lo:hi], typ[lo:hi], max_events=p["fit_max_events"])
                except ValueError:
                    f = None
                if f is not None and f["ok"]:
                    params_now = f; hawk = OnlineHawkes(f["mu"], f["alpha"], f["beta"]); last_fit = tc
                    for j in range(max(lo, hi - 800), hi):          # amorçage : les derniers événements, pour que les intensités soient « chaudes »
                        hawk.update(t_ev[j], int(typ[j]))
                    e = hi
        if hawk is None:
            continue
        while e < len(t_ev) and t_ev[e] < tc:
            hawk.update(t_ev[e], int(typ[e])); e += 1
        rho[k] = params_now["rho"]; imb[k] = hawk.imbalance(tc)
    dp = df["close"].diff().to_numpy(float); vp = vpin_series(dp, df["volume"].to_numpy(float), p["vpin_window"]); s = pd.Series(vp)
    q = s.shift(1).rolling(p["q_window"], min_periods=max(60, p["q_window"] // 5)).quantile(p["q"]).to_numpy()
    return pd.DataFrame({"rho": rho, "vpin": vp, "vpin_q": q, "imb": imb}, index=df.index)


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; F = features(df, p)
    if F is None:
        return []
    _CACHE["key"] = (p["symbol"], df.index[-1], len(df)); _CACHE["feat"] = F
    atr = atr_series(df, 14); c = df["close"].to_numpy(float); out = []; last = -10**9
    ok = (F["rho"] >= p["rho_in"]) & (F["vpin"] > F["vpin_q"]) & (F["imb"].abs() >= p["imb_min"]); ok = ok.to_numpy()
    for i in np.flatnonzero(ok):
        if i - last < p["cooldown"] or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        d = 1 if F["imb"].iloc[i] > 0 else -1; last = i
        out.append(Event(df.index[i], "bullish" if d > 0 else "bearish", float(c[i] - d * p["stop_atr"] * atr[i]), float(c[i] + d * p["target_atr"] * atr[i]), "hawk_tox",
                         {"rho": float(F["rho"].iloc[i]), "vpin": float(F["vpin"].iloc[i]), "imb": float(F["imb"].iloc[i])}))
    return out


def exit_rule(params: dict | None = None):
    p = {**PARAMS, **(params or {})}

    def rule(df: pd.DataFrame, pos) -> str | None:
        key = (p["symbol"], df.index[-1], len(df)); F = _CACHE.get("feat") if _CACHE.get("key") == key else None
        if F is None:
            F = features(df.tail(480), p)
        if F is None or not np.isfinite(F["rho"].iloc[-1]):
            return None
        return "hawk_rho_bas" if F["rho"].iloc[-1] < p["rho_out"] else None
    return rule
