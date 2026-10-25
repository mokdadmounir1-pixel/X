"""Coinbase (API publique Exchange) : barres OHLCV de crypto en LECTURE SEULE. Aucune clé, aucun ordre, aucun compte.

- `CoinbaseClient.candles` : une requête (≤ 300 barres) ; `fetch_range` : pagination sur une plage ; réessais bornés sur 429/5xx, jamais de donnée inventée.
- `CoinbaseFeed` : même interface que `live.feed.BarFeed` (barres CLÔTURÉES uniquement, chacune émise une fois) pour la simulation PAPER.
- Horloge : Coinbase est en UTC, sans décalage de courtier. Un volume Coinbase est un VRAI volume (pas des ticks).
Les frais de Coinbase (spot) sont élevés pour un compte de détail : ils sont déclarés comme HYPOTHÈSES dans la spec, jamais supposés nuls.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from ..exceptions import DataFetchError, DataValidationError
from ..live.feed import BarFeed, FeedStatus
from ..logging_utils import get_logger

log = get_logger("data.coinbase")
BASE = "https://api.exchange.coinbase.com"
GRANULARITY = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H6": 21600, "D1": 86400}
MAX_PER_CALL = 300


def default_get(url: str, timeout: float = 20.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "quantbot-readonly/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise DataFetchError(f"Coinbase injoignable : {e}") from e


class CoinbaseClient:
    def __init__(self, get: Callable[[str], tuple[int, str]] = default_get, sleep: Callable[[float], None] = time.sleep, retries: int = 4, base: str = BASE,
                 pause: float = 0.12) -> None:
        self.get, self.sleep, self.retries, self.base, self.pause = get, sleep, retries, base, pause

    def _json(self, url: str) -> Any:
        last = ""
        for attempt in range(self.retries + 1):
            status, body = self.get(url)
            if status == 200:
                try:
                    return json.loads(body)
                except json.JSONDecodeError as exc:
                    raise DataFetchError(f"Réponse Coinbase illisible : {exc}") from exc
            last = f"HTTP {status} {body[:120]}"
            if status == 429 or status >= 500:
                self.sleep(min(2.0 ** attempt, 30.0))
                continue
            break                                         # 4xx hors 429 : inutile de réessayer
        raise DataFetchError(f"Coinbase : {last}")

    def candles(self, product: str, tf: str, start: datetime, end: datetime) -> list[list[float]]:
        g = GRANULARITY[tf]
        iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = self._json(f"{self.base}/products/{product}/candles?granularity={g}&start={iso(start)}&end={iso(end)}")
        if not isinstance(rows, list):
            raise DataFetchError(f"Réponse Coinbase inattendue : {str(rows)[:120]}")
        self.sleep(self.pause)
        return rows

    def fetch_range(self, product: str, tf: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Toutes les barres [start, end[ : fenêtres de 300 barres, fusion par époque, tri croissant."""
        g, step = GRANULARITY[tf], timedelta(seconds=GRANULARITY[tf] * MAX_PER_CALL)
        parts, a = [], start
        while a < end:
            b = min(a + step, end)
            parts += self.candles(product, tf, a, b)
            a = b
        return to_frame(parts, g)


def to_frame(rows: list[list[float]], gran: int) -> pd.DataFrame:
    """[time, low, high, open, close, volume] (plus récent d'abord) -> DataFrame quantbot (index UTC naïf croissant, sans doublon)."""
    cols = ["open", "high", "low", "close", "volume", "spread", "spread_points"]
    if not rows:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="time"))
    a = pd.DataFrame(rows, columns=["t", "low", "high", "open", "close", "volume"]).drop_duplicates("t").sort_values("t")
    df = pd.DataFrame({"open": a.open.astype(float).to_numpy(), "high": a.high.astype(float).to_numpy(), "low": a.low.astype(float).to_numpy(),
                       "close": a.close.astype(float).to_numpy(), "volume": a.volume.astype(float).to_numpy(), "spread": 0.0, "spread_points": 0.0},
                      index=pd.DatetimeIndex(pd.to_datetime(a.t.to_numpy(), unit="s"), name="time"))
    bad = (df.high < df[["open", "close"]].max(axis=1) - 1e-12) | (df.low > df[["open", "close"]].min(axis=1) + 1e-12) | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    if bad.any():
        raise DataValidationError(f"{int(bad.sum())} barre(s) Coinbase incohérente(s) : refus (aucune réparation silencieuse)")
    return df


def load_utc_csv(path: str | Path) -> pd.DataFrame:
    """CSV écrit par scripts/export_coinbase.py (colonne `time` ISO UTC) -> DataFrame quantbot."""
    try:
        raw = pd.read_csv(path)
    except FileNotFoundError as exc:
        raise DataValidationError(f"CSV introuvable : {path} (lancer scripts/export_coinbase.py)") from exc
    df = raw.set_index(pd.DatetimeIndex(pd.to_datetime(raw["time"], utc=True).dt.tz_localize(None), name="time")).drop(columns=["time"])
    return df[~df.index.duplicated(keep="last")].sort_index()


class CoinbaseFeed(BarFeed):
    """Barres clôturées Coinbase avec l'interface de BarFeed (poll / new_bars / status / _fetch). Cache incrémental : seules les dernières barres sont redemandées."""
    source = "Coinbase"
    point = 1.0

    def __init__(self, product: str, timeframe: str = "M15", n_bars: int = 3000, client: Optional[CoinbaseClient] = None, clock=time.time,
                 max_gap_hours: float = 6.0, stale_after_s: float = 1800.0) -> None:
        if timeframe not in GRANULARITY:
            raise DataFetchError(f"Timeframe Coinbase inconnu : {timeframe}")
        self.mt5, self.symbol, self.tf_name, self.n_bars, self.rule = None, product, timeframe, n_bars, "utc"
        self.max_gap_hours, self.stale_after_s, self.clock = max_gap_hours, stale_after_s, clock
        self.client, self.gran, self.status = client or CoinbaseClient(), GRANULARITY[timeframe], FeedStatus()
        self._last_emitted, self._last_new_at, self._cache = None, clock(), None

    def _closed(self, df: pd.DataFrame) -> pd.DataFrame:
        now = pd.Timestamp(self.clock(), unit="s")
        return df[df.index + pd.Timedelta(seconds=self.gran) <= now]          # une barre n'est lue qu'une fois CLÔTURÉE

    def _fetch(self) -> pd.DataFrame:
        end = datetime.fromtimestamp(self.clock(), timezone.utc)
        if self._cache is None:
            start = end - timedelta(seconds=self.gran * (self.n_bars + 2))
            df = self.client.fetch_range(self.symbol, self.tf_name, start, end)
        else:
            start = self._cache.index[-1].tz_localize("UTC").to_pydatetime() - timedelta(seconds=self.gran * 3)
            df = pd.concat([self._cache, self.client.fetch_range(self.symbol, self.tf_name, start, end)])
        if df.empty:
            raise DataFetchError(f"Aucune barre Coinbase {self.symbol} {self.tf_name}")
        df = self._closed(df[~df.index.duplicated(keep="last")].sort_index()).tail(self.n_bars)
        if df.empty:
            raise DataFetchError(f"Aucune barre CLÔTURÉE {self.symbol} {self.tf_name}")
        self._cache = df
        return df.copy()
