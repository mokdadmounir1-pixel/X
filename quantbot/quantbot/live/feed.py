"""Flux de barres MT5 : barres CLÔTURÉES uniquement, chacune émise une seule fois, trous et flux figés détectés."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from ..data.mt5 import broker_clock_to_utc
from ..exceptions import DataFetchError
from ..logging_utils import get_logger

log = get_logger("live.feed")


@dataclass
class FeedStatus:
    last_bar: Optional[pd.Timestamp] = None
    stale: bool = False
    hole: Optional[tuple] = None


class BarFeed:
    def __init__(self, mt5: Any, symbol: str, timeframe: str = "M15", n_bars: int = 3000, rule: str = "eu_dst",
                 max_gap_hours: float = 120.0, stale_after_s: float = 1800.0, clock=time.time) -> None:
        self.mt5, self.symbol, self.tf_name, self.n_bars, self.rule = mt5, symbol, timeframe, n_bars, rule
        self.max_gap_hours, self.stale_after_s, self.clock = max_gap_hours, stale_after_s, clock
        tf = getattr(mt5, f"TIMEFRAME_{timeframe}", None)
        if tf is None:
            raise DataFetchError(f"Timeframe MT5 inconnu : {timeframe}")
        self.tf = tf
        self.status = FeedStatus()
        self._last_emitted: Optional[pd.Timestamp] = None
        self._last_new_at = clock()

    def _fetch(self) -> pd.DataFrame:
        # position 1 : la barre 0 (en formation) n'est JAMAIS lue ; aucune décision n'est prise sur une bougie ouverte
        rates = self.mt5.copy_rates_from_pos(self.symbol, self.tf, 1, self.n_bars)
        if rates is None or len(rates) == 0:
            raise DataFetchError(f"Aucune barre {self.symbol} {self.tf_name} : {self.mt5.last_error()}")
        raw = pd.DataFrame(list(rates))
        raw = raw.drop_duplicates("time").sort_values("time")
        clock = pd.DatetimeIndex(pd.to_datetime(raw["time"], unit="s"))
        df = pd.DataFrame({"open": raw["open"].to_numpy(float), "high": raw["high"].to_numpy(float), "low": raw["low"].to_numpy(float),
                           "close": raw["close"].to_numpy(float), "volume": raw["tick_volume"].to_numpy(float),
                           "spread_points": raw.get("spread", pd.Series(0, index=raw.index)).to_numpy(float)},
                          index=broker_clock_to_utc(clock, self.rule))
        return df[~df.index.duplicated(keep="last")].sort_index()

    def poll(self) -> Optional[pd.DataFrame]:
        """Retourne le DataFrame complet des barres clôturées s'il contient au moins UNE barre nouvelle, sinon None."""
        df = self._fetch()
        last = df.index[-1]
        gap = df.index.to_series().diff().dt.total_seconds().div(3600.0)
        holes = gap[gap > self.max_gap_hours]
        self.status.hole = (str(holes.index[-1]), float(holes.iloc[-1])) if len(holes) else None
        if self._last_emitted is not None and last <= self._last_emitted:
            self.status.stale = (self.clock() - self._last_new_at) > self.stale_after_s
            self.status.last_bar = self._last_emitted
            return None
        self._last_new_at = self.clock()
        self.status.stale = False
        self.status.last_bar = last
        return df

    def new_bars(self, df: pd.DataFrame) -> list[pd.Timestamp]:
        """Barres nouvelles de `df` depuis la dernière émission (ordre chronologique) ; marque ces barres comme émises."""
        if self._last_emitted is None:
            new = []  # démarrage : la dernière barre est de l'HISTOIRE (possiblement ancienne) ; aucune décision dessus
        else:
            new = [t for t in df.index if t > self._last_emitted]
        self._last_emitted = df.index[-1]
        return new
