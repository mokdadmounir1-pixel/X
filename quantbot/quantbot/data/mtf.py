"""Multi-timeframe SANS fuite : une barre H4/D1 n'est utilisable qu'une fois TERMINÉE.

Barres HTF construites sur la journée de marché New York (roll à 17:00 NY, horloge murale : DST-correct) :
D1 = 1 groupe/jour, H4 = 6 groupes/jour (17,21,01,05,09,13), H1 = heure murale.
Une barre de base appartenant au groupe g ne voit que les groupes < g (donc terminés, même si le dernier
membre d'un groupe n'a pas encore été « confirmé » : perte volontaire d'au plus une barre, jamais de fuite).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators.core import atr, ema

NY = "America/New_York"
ROLL_HOUR = 17


def group_keys(index: pd.DatetimeIndex, rule: str) -> np.ndarray:
    """Identifiant entier croissant du groupe HTF de chaque barre (rule : '1h', '4h', '1D')."""
    wall = pd.DatetimeIndex(index).tz_localize("UTC").tz_convert(NY).tz_localize(None)
    shifted = wall - pd.Timedelta(hours=ROLL_HOUR)
    day = shifted.floor("D")
    if rule == "1D":
        key = day
    elif rule == "4h":
        key = day + pd.to_timedelta((shifted.hour // 4) * 4, unit="h")
    elif rule == "1h":
        key = shifted.floor("h")
    else:
        raise ValueError(f"règle HTF inconnue : {rule}")
    return pd.factorize(key, sort=True)[0]


def resample_base(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Barres H1/H4 depuis le M15 (index = début du groupe, UTC naïf) ; premier et dernier groupes partiels écartés."""
    gid = group_keys(df.index, rule)
    g = df.groupby(gid)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum()})
    out.index = pd.DatetimeIndex(g.apply(lambda x: x.index[0]).to_numpy())
    for extra in ("spread", "spread_points"):
        if extra in df.columns:
            out[extra] = g[extra].mean().to_numpy()
    out = out.iloc[1:-1] if len(out) > 2 else out
    out.attrs.update(df.attrs)
    return out


def htf_state(df: pd.DataFrame, rule: str, fast: int = 20, slow: int = 50, band: float = 0.25) -> pd.Series:
    """Tendance de la dernière barre HTF TERMINÉE : +1 / -1 / 0 (EMA rapide vs lente, bande neutre = band x ATR HTF)."""
    gid = group_keys(df.index, rule)
    g = df.groupby(gid)
    htf = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last()})
    f, s, a = ema(htf["close"], fast), ema(htf["close"], slow), atr(htf, 14)
    diff = f - s
    st = np.where(np.isfinite(diff) & np.isfinite(a) & (diff.abs() > band * a), np.sign(diff), 0.0)
    prev = np.concatenate(([0.0], st[:-1]))  # le groupe g ne voit que l'état du groupe g-1
    return pd.Series(prev[gid].astype("int8"), index=df.index)


def bias(df: pd.DataFrame, rules=("4h", "1D"), **kw) -> pd.Series:
    """Biais combiné : +1 si TOUTES les tendances HTF sont haussières, -1 si toutes baissières, sinon 0 (mixte)."""
    states = np.vstack([htf_state(df, r, **kw).to_numpy() for r in rules])
    out = np.where((states == 1).all(0), 1, np.where((states == -1).all(0), -1, 0)).astype("int8")
    return pd.Series(out, index=df.index)
