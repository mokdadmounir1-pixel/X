"""Calendrier de risque : fenêtre de week-end (les plus gros gaps sont les réouvertures du dimanche soir)."""
from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


def in_weekend_blackout(ts: Any, tz: str = "Europe/Prague", cutoff_hour: int = 20) -> bool:
    """Vrai du vendredi `cutoff_hour` (heure locale) jusqu'à la fin du dimanche. `ts` naïf = UTC."""
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    local = t.tz_convert(ZoneInfo(tz))
    return local.weekday() >= 5 or (local.weekday() == 4 and local.hour >= cutoff_hour)
