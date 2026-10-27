"""Arbitrage de volatilité : volatilité RÉALISÉE (Garman-Klass) contre volatilité IMPLICITE de la chaîne d'options (ATM, échéance la plus proche), en écart centré-réduit.

Un CFD d'or ne permet PAS de négocier la volatilité : l'écart IV - RV sert de variable de RÉGIME (prime de variance élevée = marché cher en protection), pas de signal d'ordre direct. Exige une chaîne d'options RÉELLE
(`strategies/dealer_gex.load_chain`) ; sans elle, aucune valeur n'est produite.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def realized_vol(df: pd.DataFrame, window: int = 96, bars_per_year: float = 252 * 96) -> pd.Series:
    """Volatilité Garman-Klass annualisée (fraction, 0,15 = 15 %) sur `window` barres, causale."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    v = 0.5 * np.log(h / l) ** 2 - (2 * np.log(2) - 1) * np.log(c / o) ** 2
    return pd.Series(np.sqrt(np.maximum(pd.Series(v).rolling(window).mean().to_numpy() * bars_per_year, 0.0)), index=df.index)


def atm_iv(chain: pd.DataFrame, forward: float, asof: pd.Timestamp) -> float:
    """IV de la ligne la plus proche du forward parmi l'échéance non expirée la plus courte (moyenne call/put au strike le plus proche)."""
    c = chain[chain["expiry"] > asof]
    if c.empty:
        return float("nan")
    exp = c["expiry"].min(); c = c[c["expiry"] == exp]; k = c.iloc[(c["strike"] - forward).abs().argsort()[:1]]["strike"].iloc[0]
    return float(c[c["strike"] == k]["iv"].mean())


def variance_premium_z(iv: float, rv: pd.Series, window: int = 500) -> float:
    """Écart IV - RV courant, centré-réduit par la distribution de la RV récente (échelle de référence)."""
    r = rv.dropna().iloc[-window:]
    return float((iv - r.iloc[-1]) / r.std()) if len(r) > 30 and r.std() > 0 and np.isfinite(iv) else float("nan")
