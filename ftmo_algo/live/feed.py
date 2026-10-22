"""Flux de barres M5 : rejeu (historique), MT5 (direct) ; détection de flux figé + reconnexion."""
from __future__ import annotations
import time
import numpy as np
import pandas as pd
from ..timeutil import ns


class ReplayFeed:
    """Rejoue des DataFrames M5 dans l'ordre chronologique (barres clôturées uniquement)."""
    mode = "REPLAY"

    def __init__(self, dfs: dict[str, pd.DataFrame], start=None, end=None):
        ev = []
        for s, d in dfs.items():
            if start is not None:
                d = d[d.index >= start]
            if end is not None:
                d = d[d.index < end]
            t = ns(d.index)
            arr = d[["open", "high", "low", "close", "volume"] + (["spread"] if "spread" in d else [])].to_numpy("float64")
            ev.append((t, np.full(len(t), s, dtype=object), arr))
        self.cols = ["open", "high", "low", "close", "volume", "spread"]
        T = np.concatenate([e[0] for e in ev]); S = np.concatenate([e[1] for e in ev])
        o = np.argsort(T, kind="stable")
        self._T, self._S = T[o], S[o]
        self._A = np.concatenate([e[2] if e[2].shape[1] == 6 else np.c_[e[2], np.zeros(len(e[2]))] for e in ev])[o]
        self.i = 0
        self.last_bar_time = None

    def __len__(self):
        return len(self._T)

    def next(self):
        if self.i >= len(self._T):
            return None
        k = self.i; self.i += 1
        self.last_bar_time = time.time()
        return self._S[k], int(self._T[k]), dict(zip(self.cols, self._A[k]))

    def stale(self, max_age_s=0):
        return False


class MT5Feed:
    """Direct MT5 : interroge la dernière barre M5 close de chaque symbole ; reconnexion automatique."""
    mode = "DEMO"

    def __init__(self, symbols, stale_after_s=900):
        self.symbols = symbols
        self.seen = {s: 0 for s in symbols}
        self.queue = []
        self.last_bar_time = time.time()
        self.stale_after = stale_after_s
        self.ok = False

    def connect(self):
        import MetaTrader5 as mt5
        self.mt5 = mt5
        self.ok = bool(mt5.initialize())
        return self.ok

    def next(self):
        if not self.queue:
            for s in self.symbols:
                try:
                    r = self.mt5.copy_rates_from_pos(s, self.mt5.TIMEFRAME_M5, 1, 1)   # dernière barre CLOSE
                except Exception:
                    r = None
                if r is None or len(r) == 0:
                    if not self.connect():
                        time.sleep(5)           # reconnexion automatique
                    continue
                t = int(r[0]["time"]) * 10**9
                if t > self.seen[s]:
                    self.seen[s] = t
                    pt = self.mt5.symbol_info(s).point
                    self.queue.append((s, t, {"open": r[0]["open"], "high": r[0]["high"], "low": r[0]["low"],
                                              "close": r[0]["close"], "volume": r[0]["tick_volume"],
                                              "spread": r[0]["spread"] * pt}))
                    self.last_bar_time = time.time()
            if not self.queue:
                time.sleep(2)
                return "WAIT"
        return self.queue.pop(0)

    def stale(self, max_age_s=None):
        return (time.time() - self.last_bar_time) > (max_age_s or self.stale_after)
