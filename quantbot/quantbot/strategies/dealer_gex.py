"""Exposition gamma des teneurs de marché (GEX) sur l'or, calculée sur de VRAIES données d'options, fusionnée avec le repli APEX.

CE MODULE NE FABRIQUE AUCUN GEX. Il exige une chaîne d'options réelle (open interest par strike, volatilité implicite, échéance) — par ex. les options sur
futures or COMEX (GC) publiées par le CME — et refuse de tourner sans elle. Les exports MT5 n'en contiennent pas : sans ce fichier, aucun signal n'est produit.

Fichier attendu : data/options/GC_chain_<AAAA-MM-JJ>.csv, colonnes : strike, type (C|P), oi, iv (en fraction, 0,15 = 15 %), expiry (AAAA-MM-JJ).
Hypothèses DÉCLARÉES, non vérifiées sur l'or : (1) convention de signe usuelle du GEX (gamma des calls compté positif, celui des puts négatif, i.e. clients longs calls
et courts puts) ; (2) l'open interest est publié avec un jour de retard ; (3) le futur GC et l'XAUUSD CFD diffèrent d'un décalage (`basis`) à fournir.
Le GEX est un modèle de positionnement estimé, pas une observation du carnet des banques (OTC londonien exclu) : sa valeur prédictive sur l'or n'est PAS démontrée ici.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .apex import PARAMS as APEX_PARAMS, ramp, scores
from .events import Event

CONTRACT_OZ = 100.0     # onces par contrat GC

GEX_PARAMS = {**APEX_PARAMS, "stop_atr": 1.8, "rr": 3.0, "fused_min": 0.70, "w_gamma": 0.5, "cluster_atr": 1.0, "vel_bars": 4, "vel_lo": 0.5, "vel_hi": 2.0,
              "regime_scale": 0.5, "basis": 0.0, "top_k": 5}


def bs_gamma(F, K, T, sigma):
    """Gamma de Black-76 (par unité de sous-jacent). Vectorisé ; 0 si T ou sigma sont nuls."""
    F, K, T, sigma = (np.asarray(x, float) for x in np.broadcast_arrays(F, K, T, sigma))
    ok = (T > 0) & (sigma > 0) & (F > 0) & (K > 0); out = np.zeros(F.shape)
    sd = sigma * np.sqrt(np.where(ok, T, 1.0)); d1 = (np.log(np.where(ok, F, 1.0) / np.where(ok, K, 1.0)) + 0.5 * sd ** 2) / np.where(ok, sd, 1.0)
    out[ok] = (np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi) / (F * sd))[ok]
    return out


@dataclass
class GexProfile:
    spot: float
    strikes: np.ndarray            # strikes triés
    net_gex: np.ndarray            # GEX net par strike (unités : $ par 1 % de mouvement)
    total: float
    zero_gamma: float | None       # niveau de prix où le GEX total change de signe (None si pas de croisement dans la grille)
    grid: np.ndarray
    grid_total: np.ndarray

    def total_at(self, price: float) -> float:
        return float(np.interp(price, self.grid, self.grid_total))


def load_chain(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Chaîne d'options introuvable : {p}. Aucun GEX n'est fabriqué : fournissez un export réel (open interest par strike).")
    df = pd.read_csv(p); need = {"strike", "type", "oi", "iv", "expiry"}
    if not need <= set(df.columns):
        raise ValueError(f"Colonnes manquantes : {sorted(need - set(df.columns))}")
    df["type"] = df["type"].str.upper().str[0]; df["expiry"] = pd.to_datetime(df["expiry"])
    return df[(df.oi > 0) & (df.iv > 0)].reset_index(drop=True)


def _gex_at(chain: pd.DataFrame, F: np.ndarray, asof: pd.Timestamp) -> np.ndarray:
    """GEX total pour chaque prix F d'une grille : somme sur la chaîne de signe x gamma x OI x contrat x F² x 1 %."""
    T = np.maximum((chain["expiry"] - asof).dt.total_seconds().to_numpy() / (365.25 * 86400), 0.0)
    sign = np.where(chain["type"].to_numpy() == "C", 1.0, -1.0); K = chain["strike"].to_numpy(float); iv = chain["iv"].to_numpy(float); oi = chain["oi"].to_numpy(float)
    return np.array([float((sign * bs_gamma(f, K, T, iv) * oi * CONTRACT_OZ * f * f * 0.01).sum()) for f in F])


def gex_profile(chain: pd.DataFrame, spot_fut: float, asof: pd.Timestamp, grid_pct: float = 0.06, n_grid: int = 121) -> GexProfile:
    grid = np.linspace(spot_fut * (1 - grid_pct), spot_fut * (1 + grid_pct), n_grid); tot = _gex_at(chain, grid, asof)
    sg = np.sign(tot); cross = np.flatnonzero(sg[:-1] * sg[1:] < 0); zg = None
    if cross.size:
        k = cross[np.argmin(np.abs(grid[cross] - spot_fut))]; zg = float(grid[k] - tot[k] * (grid[k + 1] - grid[k]) / (tot[k + 1] - tot[k]))
    strikes = np.sort(chain["strike"].unique()); T = np.maximum((chain["expiry"] - asof).dt.total_seconds().to_numpy() / (365.25 * 86400), 0.0)
    contrib = np.where(chain["type"].to_numpy() == "C", 1.0, -1.0) * bs_gamma(spot_fut, chain["strike"].to_numpy(float), T, chain["iv"].to_numpy(float)) * chain["oi"].to_numpy(float) * CONTRACT_OZ * spot_fut ** 2 * 0.01
    net = pd.Series(contrib).groupby(chain["strike"].to_numpy()).sum().reindex(strikes).to_numpy()
    return GexProfile(float(spot_fut), strikes, net, float(_gex_at(chain, np.array([spot_fut]), asof)[0]), zg, grid, tot)


def g_score(price: float, prof: GexProfile, atr: float, velocity_atr: float, p: dict = GEX_PARAMS) -> dict:
    """Score de squeeze G dans [0, 1], produit géométrique de trois facteurs continus :
    prox  : proximité (en ATR) du plus proche des `top_k` strikes à plus forte |GEX| ; regime : gamma NÉGATIF (amplificateur) autour du prix ; vel : vitesse récente (en ATR)."""
    if atr <= 0 or not np.isfinite(price):
        return {"G": 0.0, "prox": 0.0, "regime": 0.0, "vel": 0.0}
    top = prof.strikes[np.argsort(-np.abs(prof.net_gex))[: p["top_k"]]]
    d = float(np.min(np.abs(top - price))) / atr if len(top) else math.inf
    prox = math.exp(-((d / p["cluster_atr"]) ** 2))
    scale = max(float(np.max(np.abs(prof.grid_total))), 1e-12); regime = float(1.0 / (1.0 + math.exp(prof.total_at(price) / scale / p["regime_scale"])))   # < 0 -> proche de 1
    vel = float(ramp(abs(velocity_atr), p["vel_lo"], p["vel_hi"]))
    return {"G": float((prox * regime * vel) ** (1.0 / 3.0)), "prox": prox, "regime": regime, "vel": vel}


def fused_score(S: float, G: float, w: float) -> float:
    """Synergie continue : moyenne géométrique pondérée S^(1-w) x G^w (un facteur nul annule le setup, aucun test binaire)."""
    return float((max(S, 0.0) ** (1.0 - w)) * (max(G, 0.0) ** w))


def events(df: pd.DataFrame, profiles: dict, p: dict | None = None) -> list[Event]:
    """APEX PULLBACK x GEX. `profiles` : {date (Timestamp normalisé) -> GexProfile} calculé SUR LES DONNÉES DE LA VEILLE (open interest publié avec un jour de retard).
    Les jours sans profil réel n'émettent AUCUN événement. Stop 1,8 ATR, cible 3 R."""
    p = {**GEX_PARAMS, **(p or {})}; sc = scores(df, p); atr = sc["atr"]; c = df["close"].to_numpy(float)
    sess = (df.index.hour >= 7) & (df.index.hour < 17); days = df.index.normalize(); out, last = [], -10**9
    for i in range(p["ema_slow"] + p["atr_long"], len(df)):
        prof = profiles.get(days[i])
        if prof is None or not sess[i] or not np.isfinite(atr[i]) or i - last < p["cooldown"]:
            continue
        vel = (c[i] - c[i - p["vel_bars"]]) / atr[i]
        for side, sg, direction in (("bull", 1, "bullish"), ("bear", -1, "bearish")):
            S = sc[side]["S"][i]
            if not np.isfinite(S) or S <= 0:
                continue
            g = g_score(c[i] + p["basis"], prof, atr[i], vel, p)        # |vitesse| : le sens est porté par le côté du repli (S)
            f = fused_score(float(S), g["G"], p["w_gamma"])
            if f >= p["fused_min"]:
                stop = c[i] - sg * p["stop_atr"] * atr[i]; tgt = c[i] + sg * p["rr"] * p["stop_atr"] * atr[i]
                out.append(Event(df.index[i], direction, stop, tgt, f"apex_gex_{'long' if sg > 0 else 'short'}", {"confidence": min(f, 1.0), "S": float(S), **g, "fused": f})); last = i
                break
    return out
