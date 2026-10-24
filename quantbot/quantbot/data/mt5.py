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


_DST_RULES = {"eu_dst": ("Europe/Athens", pd.Timedelta(hours=3)), "us_dst": ("America/New_York", pd.Timedelta(hours=-4))}


def broker_clock_to_utc(clock: pd.DatetimeIndex, rule: str = "eu_dst") -> pd.DatetimeIndex:
    """Horloge courtier (naïve) -> UTC naïf. UTC+3 en heure d'été, UTC+2 sinon.

    rule='eu_dst' (DÉFAUT) : l'été suit le calendrier EUROPÉEN (mesuré : 98,8 % des pauses quotidiennes de l'or
    reprennent à 18:00 New York, contre 92,5 % avec le calendrier US ; l'écart tient aux ~4 semaines/an où les
    deux calendriers divergent). 'us_dst' : ancien choix des specs v0/v1/v2 (conservé pour reproduire ces essais).
    'fixedN' : décalage fixe.
    """
    clock = pd.DatetimeIndex(clock)
    if rule.startswith("fixed"):
        return clock - pd.Timedelta(hours=int(rule.replace("fixed", "")))
    if rule not in _DST_RULES:
        raise ValueError(f"règle inconnue : {rule}")
    zone, summer_offset = _DST_RULES[rule]
    guess = (clock - pd.Timedelta(hours=3)).tz_localize("UTC")  # hypothèse « été »
    local = guess.tz_convert(zone)
    is_dst = (local.tz_localize(None) - guess.tz_localize(None)) == summer_offset
    return pd.DatetimeIndex(np.where(is_dst, clock - pd.Timedelta(hours=3), clock - pd.Timedelta(hours=2)))


def load_mt5_csv(path: str | Path, rule: str = "eu_dst") -> pd.DataFrame:
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


def gap_quantile(df: pd.DataFrame, q: float = 0.999, max_gap_hours: float = 120.0) -> float:
    """Quantile q de |ouverture / clôture précédente - 1| (gaps de reprise, week-ends, annonces).

    Les trous de données (> max_gap_hours) sont exclus : ce sont des données manquantes, pas du risque de marché.
    """
    gap_h = df.index.to_series().diff().dt.total_seconds().div(3600.0)
    g = (df["open"] / df["close"].shift(1) - 1.0).abs()[gap_h <= max_gap_hours].dropna()
    return float(g.quantile(q)) if len(g) else float("nan")


def leverage_cap_from_gaps(df: pd.DataFrame, loss_budget: float = 0.01, q: float = 0.999, lo: float = 0.25,
                           hi: float = 5.0, max_gap_hours: float = 120.0) -> float:
    """Levier maximal tel qu'un gap extrême (quantile q) coûte au plus `loss_budget` du capital."""
    g = gap_quantile(df, q, max_gap_hours)
    if not np.isfinite(g) or g <= 0:
        return lo
    return float(min(hi, max(lo, loss_budget / g)))


def costs_from_frame(df: pd.DataFrame, since: str | None = None) -> dict:
    """Spread médian (fraction du prix) mesuré ; None si la colonne n'est pas fiable (>30 % de zéros)."""
    d = df if since is None else df[df.index >= since]
    if "spread" not in d.columns or len(d) == 0:
        return {"spread_frac": None, "reliable": False, "zero_share": None}
    zero = float((d["spread"] <= 0).mean())
    reliable = zero < 0.30
    frac = float((d["spread"] / d["close"]).median()) if reliable else None
    return {"spread_frac": frac, "reliable": reliable, "zero_share": round(zero, 3)}
