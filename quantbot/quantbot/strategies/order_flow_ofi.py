"""Flux d'ordres : OFI (Cont-Kukanov-Stoikov) sur des cotations RÉELLES de carnet, proxy de flux par ticks, proxy d'absorption par barres.

Vérité des données : MetaTrader 5 CFD n'expose en général NI profondeur de carnet NI tailles bid/ask (seulement bid/ask et un volume de ticks). Donc :
  - `ofi_l1` / `imbalance` exigent de VRAIES tailles bid/ask (flux de profondeur d'un fournisseur de données) ; sans elles, aucune valeur n'est fabriquée ;
  - `tick_flow_imbalance` est un PROXY (sens des révisions de cotation), pas un OFI ;
  - `absorption_score` est un PROXY d'absorption (volume élevé / déplacement faible) ; il NE PROUVE PAS la présence d'un iceberg (invisible par construction).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ofi_l1(bid, ask, bid_sz, ask_sz) -> np.ndarray:
    """OFI événement par événement (Cont, Kukanov, Stoikov 2014) sur le meilleur niveau : e_n = I{Pb_n >= Pb_n-1} qb_n - I{Pb_n <= Pb_n-1} qb_n-1 - I{Pa_n <= Pa_n-1} qa_n + I{Pa_n >= Pa_n-1} qa_n-1.
    Positif = pression acheteuse. Le premier événement vaut 0."""
    pb, pa, qb, qa = (np.asarray(x, float) for x in (bid, ask, bid_sz, ask_sz)); e = np.zeros(len(pb))
    if len(pb) > 1:
        db, da = pb[1:] - pb[:-1], pa[1:] - pa[:-1]
        e[1:] = np.where(db >= 0, qb[1:], 0.0) - np.where(db <= 0, qb[:-1], 0.0) - np.where(da <= 0, qa[1:], 0.0) + np.where(da >= 0, qa[:-1], 0.0)
    return e


def imbalance(ofi_events, window: int, depth_norm) -> np.ndarray:
    """I_ofi dans [-1, 1] : somme glissante de l'OFI sur `window` événements / (somme glissante de la profondeur + eps), bornée par tanh."""
    s = pd.Series(np.asarray(ofi_events, float)).rolling(window).sum(); d = pd.Series(np.asarray(depth_norm, float)).rolling(window).sum()
    return np.tanh((s / (d + 1e-12)).to_numpy())


def tick_flow_imbalance(bid, ask, window: int) -> np.ndarray:
    """PROXY dans [-1, 1] : (révisions de milieu de cotation à la hausse - à la baisse) / total, sur `window` ticks. Pas de tailles : ce n'est pas un OFI."""
    m = (np.asarray(bid, float) + np.asarray(ask, float)) / 2.0; d = np.sign(np.diff(m, prepend=m[0]))
    up = pd.Series((d > 0).astype(float)).rolling(window).sum(); dn = pd.Series((d < 0).astype(float)).rolling(window).sum()
    return ((up - dn) / (up + dn).replace(0, np.nan)).fillna(0.0).to_numpy()


def _ramp(x, lo, hi):
    return np.clip((np.asarray(x, float) - lo) / (hi - lo), 0.0, 1.0)


def absorption_score(df: pd.DataFrame, atr: np.ndarray, vol_n: int = 50, vol_lo: float = 1.0, vol_hi: float = 2.5, rng_lo: float = 0.3, rng_hi: float = 1.0) -> np.ndarray:
    """PROXY A dans [0, 1] : volume de ticks élevé (rampe sur volume/médiane glissante) ET déplacement faible (1 - rampe de amplitude/ATR), produit continu."""
    v = df["volume"].to_numpy(float); med = pd.Series(v).rolling(vol_n).median().to_numpy()
    vol_hi_f = _ramp(v / med, vol_lo, vol_hi); small_move = 1.0 - _ramp((df["high"].to_numpy(float) - df["low"].to_numpy(float)) / atr, rng_lo, rng_hi)
    return np.sqrt(vol_hi_f * small_move)


def release_direction_score(df: pd.DataFrame, a: np.ndarray, atr: np.ndarray, lookback: int = 6, thr: float = 0.5, hi: float = 1.5) -> np.ndarray:
    """Après une zone d'absorption (max de A sur `lookback` barres PRÉCÉDENTES), score signé [-1, 1] de la sortie : (close - open) / ATR de la barre courante, pondéré par l'absorption précédente.
    Positif = sortie haussière. C'est le « breakout » après absorption, observé APRÈS coup (pas anticipé)."""
    prev = pd.Series(a).shift(1).rolling(lookback).max().to_numpy(); move = (df["close"].to_numpy(float) - df["open"].to_numpy(float)) / atr
    return np.clip(np.sign(move) * _ramp(np.abs(move), thr, hi) * prev, -1.0, 1.0)


def micro_price(bid, ask, bid_sz, ask_sz) -> np.ndarray:
    """Micro-prix P = Pb x Va/(Vb+Va) + Pa x Vb/(Vb+Va) : tiré vers le côté le plus mince du carnet. Exige de VRAIES tailles ; NaN si la somme des tailles est nulle (rien n'est inventé)."""
    pb, pa, vb, va = (np.asarray(x, float) for x in (bid, ask, bid_sz, ask_sz)); tot = vb + va
    return np.where(tot > 0, (pb * va + pa * vb) / np.where(tot > 0, tot, 1.0), np.nan)


def aggression_ratio(bid, ask, window: int = 10) -> np.ndarray:
    """PROXY de toxicité de flux (VPIN simplifié) dans [0, 1] : sur les `window` derniers ticks, |achats agressifs - ventes agressives| / total, classés par la règle du tick
    (mouvement du milieu de cotation). Sans ruban de transactions réel, ce n'est PAS un VPIN ; sert de garde-fou grossier."""
    m = (np.asarray(bid, float) + np.asarray(ask, float)) / 2.0; d = np.sign(np.diff(m, prepend=m[0]))
    b = pd.Series((d > 0).astype(float)).rolling(window).sum(); s = pd.Series((d < 0).astype(float)).rolling(window).sum()
    return ((b - s).abs() / (b + s).replace(0, np.nan)).fillna(0.0).to_numpy()


def toxicity_pause(ratio: float, threshold: float = 0.8, softness: float = 0.1) -> float:
    """Facteur continu dans [0, 1] à multiplier à la taille : 1 sous le seuil, décroît vers 0 au-dessus (rampe de largeur `softness`), pas de coupure binaire."""
    return float(np.clip(1.0 - (ratio - threshold) / softness, 0.0, 1.0))
