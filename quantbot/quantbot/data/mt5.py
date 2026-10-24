"""Export MetaTrader 5 (CSV) : horloge du courtier -> UTC, spreads, trous.

Le CSV fourni contient `time` (= horloge courtier − 3 h FIXE, donc fausse d'1 h en hiver quand le
serveur est en UTC+2) et `time_broker_epoch` (horloge courtier brute). On reconstruit l'UTC avec la
règle des serveurs « fin de journée New York » : UTC+3 pendant l'heure d'été américaine, UTC+2 sinon.
Contrôle de cohérence : la semaine FX doit s'ouvrir dimanche 21:00 UTC (été) / 22:00 UTC (hiver).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..exceptions import DataValidationError
from ..logging_utils import get_logger
from .validation import validate_ohlcv

log = get_logger("data.mt5")


def broker_clock_to_utc(clock: pd.DatetimeIndex, rule: str = "us_dst") -> pd.DatetimeIndex:
    """Horloge courtier (naïve) -> UTC naïf. rule: 'us_dst' (UTC+3 en DST US, UTC+2 sinon) ou 'fixed+N'."""
    clock = pd.DatetimeIndex(clock)
    if rule.startswith("fixed"):
        return clock - pd.Timedelta(hours=int(rule.replace("fixed", "")))
    if rule != "us_dst":
        raise ValueError(f"règle inconnue : {rule}")
    guess = (clock - pd.Timedelta(hours=3)).tz_localize("UTC")  # hypothèse « été »
    ny = guess.tz_convert("America/New_York")
    is_dst = (ny.tz_localize(None) - guess.tz_localize(None)) == pd.Timedelta(hours=-4)
    return pd.DatetimeIndex(np.where(is_dst, clock - pd.Timedelta(hours=3), clock - pd.Timedelta(hours=2)))


def load_mt5_csv(path: str | Path, rule: str = "us_dst") -> pd.DataFrame:
    """Charge l'export, index = UTC naïf reconstruit. Colonnes : OHLC, volume (ticks), spread (prix), spread_points."""
    try:
        raw = pd.read_csv(path)
    except FileNotFoundError as exc:
        raise DataValidationError(f"CSV introuvable : {path}") from exc
    need = {"time_broker_epoch", "open", "high", "low", "close"}
    if not need <= set(raw.columns):
        raise DataValidationError(f"Colonnes manquantes : {sorted(need - set(raw.columns))}")
    clock = pd.DatetimeIndex(pd.to_datetime(raw["time_broker_epoch"], unit="s"))
    df = raw[["open", "high", "low", "close"]].copy()
    df["volume"] = raw["tick_volume"] if "tick_volume" in raw else 0.0
    df["spread"] = raw["spread"] if "spread" in raw else 0.0
    df["spread_points"] = raw["spread_points"] if "spread_points" in raw else 0.0
    df.index = broker_clock_to_utc(clock, rule)
    df = df[~df.index.duplicated(keep="last")].sort_index()  # transitions : 1 h ambiguë possible
    out = validate_ohlcv(df[["open", "high", "low", "close", "volume"]], repair=False)
    out["spread"] = df["spread"].to_numpy()[: len(out)] if len(out) == len(df) else df["spread"].reindex(out.index)
    out["spread_points"] = df["spread_points"].reindex(out.index)
    out.attrs.update({"source": f"MT5:{Path(path).name}", "clock_rule": rule})
    return out


def find_holes(df: pd.DataFrame, max_gap_hours: float = 120.0) -> list[dict]:
    """Trous de données (au-delà des week-ends/jours fériés), avec le saut de prix qu'ils cachent."""
    gap_h = df.index.to_series().diff().dt.total_seconds().div(3600.0)
    out = []
    for i in np.flatnonzero(gap_h.to_numpy() > max_gap_hours):
        out.append({"from": str(df.index[i - 1]), "to": str(df.index[i]), "hours": round(float(gap_h.iloc[i]), 1),
                    "price_jump_pct": round(float(df["open"].iloc[i] / df["close"].iloc[i - 1] - 1) * 100, 2)})
    return out


def weekly_open_check(df: pd.DataFrame) -> dict:
    """Heure UTC (décimale) de la première barre de chaque semaine, médiane été vs hiver.

    Pour un instrument FX/CFD qui s'ouvre à 17:00 New York : ~21:00 UTC en été, ~22:00 en hiver (écart d'1 h).
    Un écart nul entre saisons trahit une conversion horaire à décalage fixe.
    """
    s = df.index.to_series()
    key = (s + pd.Timedelta(hours=12)).dt.strftime("%G-%V")  # dimanche soir -> semaine de trading suivante
    wk = s.groupby(key).min()
    hh = wk.dt.hour + wk.dt.minute / 60.0
    mo = wk.dt.month
    summer, winter = hh[mo.isin([6, 7, 8])], hh[mo.isin([12, 1, 2])]
    return {"summer_median_utc": float(summer.median()) if len(summer) else None,
            "winter_median_utc": float(winter.median()) if len(winter) else None,
            "shift_hours": (float(winter.median() - summer.median()) if len(summer) and len(winter) else None)}


def costs_from_frame(df: pd.DataFrame, since: str | None = None) -> dict:
    """Spread médian (fraction du prix) mesuré ; None si la colonne n'est pas fiable (>30 % de zéros)."""
    d = df if since is None else df[df.index >= since]
    if "spread" not in d.columns or len(d) == 0:
        return {"spread_frac": None, "reliable": False, "zero_share": None}
    zero = float((d["spread"] <= 0).mean())
    reliable = zero < 0.30
    frac = float((d["spread"] / d["close"]).median()) if reliable else None
    return {"spread_frac": frac, "reliable": reliable, "zero_share": round(zero, 3)}
