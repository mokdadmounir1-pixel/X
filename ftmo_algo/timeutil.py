import numpy as np
import pandas as pd


def ns(idx) -> np.ndarray:
    """Index/Series de dates -> int64 en nanosecondes (indépendant de l'unité pandas)."""
    idx = pd.DatetimeIndex(idx)
    return idx.as_unit("ns").asi8


# Heure SERVEUR du courtier (FTMO/MT5 : GMT+2 l'hiver, GMT+3 l'été, bascule alignée sur New York). [HYPOTHÈSE] à vérifier par courtier.
SERVER_TZ = "Europe/Athens"


def server_clock(t_ns: np.ndarray, tz: str = SERVER_TZ):
    """(minute du jour, jour de semaine lundi=0, identifiant de jour) en heure serveur, pour des instants ns UTC."""
    loc = pd.to_datetime(np.asarray(t_ns, dtype="int64"), utc=True).tz_convert(tz)
    mn = (loc.hour * 60 + loc.minute).to_numpy().astype("int32")
    dow = loc.dayofweek.to_numpy().astype("int8")
    day = (loc.tz_localize(None).normalize().as_unit("ns").asi8 // 86_400_000_000_000).astype("int64")
    return mn, dow, day
