"""Calendrier d'annonces : CSV utilisateur (time,name,importance) ou règle NFP par défaut
[HYPOTHÈSE : seule la règle « premier vendredi du mois 08:30 New York » est codée ; fournir un CSV
pour CPI/FOMC/BCE réels]."""
from __future__ import annotations
import numpy as np
import pandas as pd
from ..timeutil import ns


class NewsCalendar:
    def __init__(self, times_ns: np.ndarray, names: list[str] | None = None, source: str = "rule:NFP"):
        o = np.argsort(times_ns)
        self.t = np.asarray(times_ns, dtype="int64")[o]
        self.names = [(names or ["event"] * len(o))[i] for i in o]
        self.source = source

    @classmethod
    def default(cls, start: pd.Timestamp, end: pd.Timestamp) -> "NewsCalendar":
        from ..data.synth import nfp_times
        ts = nfp_times(start, end + pd.Timedelta(days=45))   # un calendrier est publié à l'avance
        return cls(np.array([t.value for t in ts], dtype="int64"), ["NFP"] * len(ts))

    @classmethod
    def from_csv(cls, path: str) -> "NewsCalendar":
        df = pd.read_csv(path)
        t = pd.to_datetime(df["time"], utc=True)
        return cls(ns(t), list(df.get("name", ["event"] * len(df))), source=f"csv:{path}")

    def masks(self, t_open_ns: np.ndarray, bar_ns: int, pre_min=30, post_min=15, cost_bars=6):
        """block[i]: bougie dans [événement-pre, événement+post] ; mult[i]: majorant de coûts."""
        n = len(t_open_ns)
        block = np.zeros(n, bool); mult = np.ones(n)
        since = np.full(n, 1e9)  # minutes depuis le dernier événement
        if len(self.t) == 0:
            return block, mult, since
        k = np.searchsorted(self.t, t_open_ns, side="right") - 1
        ok = k >= 0
        since[ok] = (t_open_ns[ok] - self.t[k[ok]]) / 6e10
        nxt = np.searchsorted(self.t, t_open_ns, side="left")
        until = np.full(n, 1e9)
        ok2 = nxt < len(self.t)
        until[ok2] = (self.t[nxt[ok2]] - t_open_ns[ok2]) / 6e10
        block = (until <= pre_min) | (since < post_min)
        mult = np.where((until <= bar_ns / 6e10) | (since < cost_bars * bar_ns / 6e10), 3.0, 1.0)
        return block, mult, since

    def next_events(self, now_ns: int, k=5):
        i = np.searchsorted(self.t, now_ns)
        return [(int(self.t[j]), self.names[j]) for j in range(i, min(i + k, len(self.t)))]
