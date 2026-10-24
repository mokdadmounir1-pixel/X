"""Validation / nettoyage des données OHLCV."""
from __future__ import annotations

import pandas as pd

from ..exceptions import DataValidationError
from ..logging_utils import get_logger

log = get_logger("data.validation")
REQUIRED = ("open", "high", "low", "close")


def validate_ohlcv(df: pd.DataFrame, repair: bool = False, min_rows: int = 1) -> pd.DataFrame:
    """Retourne un DataFrame propre ou lève DataValidationError.

    repair=False : toute anomalie est une erreur.
    repair=True  : doublons/NaN supprimés, incohérences high/low corrigées (loggé).
    """
    if not isinstance(df, pd.DataFrame):
        raise DataValidationError("Un DataFrame est attendu")
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    missing = [c for c in REQUIRED if c not in out.columns]
    if missing:
        raise DataValidationError(f"Colonnes manquantes : {missing}")
    if "volume" not in out.columns:
        out["volume"] = 0.0
    out = out[list(REQUIRED) + ["volume"]].astype(float)
    if not isinstance(out.index, pd.DatetimeIndex):
        raise DataValidationError("L'index doit être un DatetimeIndex")

    if not out.index.is_monotonic_increasing:
        if not repair:
            raise DataValidationError("Index non trié")
        out = out.sort_index()
    dup = out.index.duplicated()
    if dup.any():
        if not repair:
            raise DataValidationError(f"{int(dup.sum())} horodatages dupliqués")
        log.warning("%d doublons supprimés", int(dup.sum()))
        out = out[~dup]
    nan = out[list(REQUIRED)].isna().any(axis=1)
    if nan.any():
        if not repair:
            raise DataValidationError(f"{int(nan.sum())} lignes avec NaN")
        log.warning("%d lignes NaN supprimées", int(nan.sum()))
        out = out[~nan]
    if (out[list(REQUIRED)] <= 0).any().any():
        raise DataValidationError("Prix <= 0 détectés")

    top = out[["open", "close"]].max(axis=1)
    bottom = out[["open", "close"]].min(axis=1)
    bad = (out["high"] < top) | (out["low"] > bottom) | (out["high"] < out["low"])
    if bad.any():
        if not repair:
            raise DataValidationError(f"{int(bad.sum())} bougies incohérentes (high/low)")
        log.warning("%d bougies corrigées", int(bad.sum()))
        out["high"] = pd.concat([out["high"], top], axis=1).max(axis=1)
        out["low"] = pd.concat([out["low"], bottom], axis=1).min(axis=1)

    if len(out) < min_rows:
        raise DataValidationError(f"Pas assez de lignes : {len(out)} < {min_rows}")
    return out
