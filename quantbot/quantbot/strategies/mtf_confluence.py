"""Analyse multi-temporelle descendante (D1 -> H4 -> H1 -> M15) : confluence continue, sans fuite, sans règle binaire.

Hiérarchie : chaque échelle donne un score de tendance dans [0, 1] dans le sens du trade ; le déclencheur M15 est le score de repli APEX (S). Ω est une moyenne GÉOMÉTRIQUE PONDÉRÉE :
un score nul à une échelle (par ex. la tendance D1 opposée) annule le setup — c'est la règle « pas de contre-tendance » sans test booléen, et aucune échelle ne compense une autre.
Causalité : une barre HTF n'est utilisable qu'une fois TERMINÉE (`data.mtf` / `smc.htf_arrays`) ; testé en altérant la barre HTF en cours.
Échelles inférieures (M5, M1, ticks) : non utilisées ici, faute de données exportées ; le module accepte d'autres règles dès qu'elles existent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .apex import PARAMS as APEX_PARAMS, ramp, scores
from .events import Event
from .smc import htf_arrays, wilder_atr

PARAMS = {**APEX_PARAMS, "stop_atr": 1.8, "rr": 3.0, "omega_min": 0.70,
          "scales": {"1D": {"fast": 10, "slow": 30, "k": 1.5, "w": 0.15}, "4h": {"fast": 20, "slow": 50, "k": 1.5, "w": 0.20}, "1h": {"fast": 20, "slow": 50, "k": 1.5, "w": 0.20}},
          "w_trigger": 0.35, "w_regime": 0.10, "vol_lo": 1.5, "vol_hi": 2.5, "vol_window": 20}


def htf_trend(df: pd.DataFrame, rule: str, fast: int, slow: int, k: float) -> dict:
    """Pour chaque barre de base : score de tendance haussier/baissier [0, 1] de la dernière barre HTF TERMINÉE (NaN avant la première) + ratio d'ATR HTF."""
    a = htf_arrays(df, rule); c = pd.Series(a["c"]); atr = wilder_atr(a["h"], a["l"], a["c"], 14)
    ef, es = c.ewm(span=fast, adjust=False).mean().to_numpy(), c.ewm(span=slow, adjust=False).mean().to_numpy()
    spread = (ef - es) / atr; up = ramp(spread, 0.0, k) * (c.to_numpy() > es); dn = ramp(-spread, 0.0, k) * (c.to_numpy() < es)
    ratio = atr / pd.Series(atr).rolling(20).mean().to_numpy()
    done = a["done_at"][:-1]                                            # done_at[g] = indice de base où le groupe g est terminé (le dernier groupe ne l'est jamais)
    pos = np.searchsorted(done, np.arange(len(df)), side="right") - 1    # dernier groupe terminé à chaque barre de base
    pick = lambda x: np.where(pos >= 0, x[np.maximum(pos, 0)], np.nan)
    return {"bull": pick(up), "bear": pick(dn), "atr_ratio": pick(ratio)}


def omega_series(df: pd.DataFrame, p: dict) -> dict:
    """Ω haussier et baissier pour chaque barre, avec le détail des scores par échelle."""
    sc = scores(df, p); out = {"atr": sc["atr"]}; trends = {r: htf_trend(df, r, s["fast"], s["slow"], s["k"]) for r, s in p["scales"].items()}
    ratio = trends["1D"]["atr_ratio"]; V = 1.0 - ramp(ratio, p["vol_lo"], p["vol_hi"])           # expansion de volatilité D1 : amortit tout
    weights = {"S": p["w_trigger"], "V": p["w_regime"], **{r: s["w"] for r, s in p["scales"].items()}}; tot = sum(weights.values())
    for side in ("bull", "bear"):
        parts = {"S": sc[side]["S"], "V": V, **{r: trends[r][side] for r in p["scales"]}}
        logs = sum((weights[k] / tot) * np.log(np.clip(v, 1e-12, 1.0)) for k, v in parts.items())
        valid = np.all([np.isfinite(v) for v in parts.values()], axis=0)
        out[side] = {"omega": np.where(valid, np.exp(logs), np.nan), "parts": parts}
    return out


def events(df: pd.DataFrame, params: dict | None = None) -> list[Event]:
    p = {**PARAMS, **(params or {})}; om = omega_series(df, p); atr = om["atr"]; c = df["close"].to_numpy(float)
    sess = (df.index.hour >= 7) & (df.index.hour < 17); out, last = [], -10**9
    for i in range(p["ema_slow"] + p["atr_long"], len(df)):
        if not sess[i] or not np.isfinite(atr[i]) or i - last < p["cooldown"]:
            continue
        ob, os_ = om["bull"]["omega"][i], om["bear"]["omega"][i]
        side, o = ("bull", ob) if np.isfinite(ob) and ob >= p["omega_min"] and ob >= (os_ if np.isfinite(os_) else 0) else (("bear", os_) if np.isfinite(os_) and os_ >= p["omega_min"] else (None, None))
        if side is None:
            continue
        sg = 1 if side == "bull" else -1; stop = c[i] - sg * p["stop_atr"] * atr[i]; tgt = c[i] + sg * p["rr"] * p["stop_atr"] * atr[i]
        meta = {"confidence": float(min(o, 1.0)), "omega": float(o), **{f"s_{k}": float(v[i]) for k, v in om[side]["parts"].items()}}
        out.append(Event(df.index[i], "bullish" if sg > 0 else "bearish", stop, tgt, f"mtf_{'long' if sg > 0 else 'short'}", meta)); last = i
    return out
