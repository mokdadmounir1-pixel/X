"""Construction des événements d'une stratégie à règles explicites depuis sa définition de spec (partagé par l'interface ; les scripts ont leur copie)."""
from __future__ import annotations

import pandas as pd

from . import amd, fvg, orb, vwap


def events_for(name: str, scfg: dict, df: pd.DataFrame) -> list:
    if name == "amd":
        return amd.events(df, {**amd.PARAMS, **{k: tuple(v) if isinstance(v, list) else v for k, v in scfg["params"].items()}})
    if name == "vwap":
        return vwap.events(df, scfg["params"])
    if name == "orb":
        return orb.events(df, scfg["params"])
    return fvg.events(df, scfg["rule"], scfg["params"])
