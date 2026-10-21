"""Un agent = un algo + son compte, alimenté par la MÊME logique que le backtest (ALGOS[...].generate + Sim)."""
from __future__ import annotations
from dataclasses import replace
import pandas as pd
from ..algos.context import Ctx
from ..algos.library import ALGOS, EXIT_VARIANTS
from ..data.quality import resample_ohlc
from ..engine.guardian import PropProfile
from ..engine.sim import Sim, SimConfig
from ..instruments import SPECS
from ..research.wf import parse_vkey
from ..timeutil import ns

M5_NS = 300 * 10**9


class SharedData:
    """Barres M5 reçues + contexte M15 calculé UNE fois par barre pour tous les agents."""

    def __init__(self, symbols, news=None, window_bars: int | None = 12000):
        self.m5 = {s: [] for s in symbols}
        self.news, self.window = news, window_bars
        self._ctx: dict = {}

    def preload(self, sym, df: pd.DataFrame):
        cols = ["open", "high", "low", "close", "volume"]
        sp = df["spread"].to_numpy() if "spread" in df else [0.0] * len(df)
        self.m5[sym] = list(zip(ns(df.index).tolist(), *(df[c].to_numpy().tolist() for c in cols), list(sp)))

    def add(self, sym, t_ns, bar) -> bool:
        a = self.m5[sym]
        a.append((t_ns, bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"], bar.get("spread", 0.0)))
        if self.window and len(a) > self.window:
            del a[: len(a) - self.window]
        return ((t_ns + M5_NS) // 10**9) % 900 == 0

    def ctx(self, sym):
        key = (sym, len(self.m5[sym]), self.m5[sym][-1][0])
        if self._ctx.get(sym, (None,))[0] == key:
            return self._ctx[sym][1]
        a = self.m5[sym]
        df = pd.DataFrame(a, columns=["t", "open", "high", "low", "close", "volume", "spread"])
        df.index = pd.to_datetime(df.pop("t"), unit="ns", utc=True)
        df.index.name = "time"
        if not (df["spread"] > 0).any():
            df = df.drop(columns=["spread"])
        m15 = resample_ohlc(df, "M15").drop(columns=["close_time"])
        m15 = m15[ns(m15.index) + 900 * 10**9 <= a[-1][0] + M5_NS]        # barres M15 closes uniquement
        c = Ctx(sym, m15, SPECS[sym], self.news) if len(m15) >= 300 else None
        self._ctx[sym] = (key, c)
        return c


class Agent:
    def __init__(self, name: str, algo: str, variant: str | None, symbols: list[str], profile: PropProfile,
                 cfg: SimConfig, news=None, journal=None, shared: SharedData | None = None, sink=None):
        self.name, self.algo, self.symbols = name, algo, symbols
        self.params, self.exit_name = parse_vkey(variant) if variant else (ALGOS[algo].default, "fixed3")
        self.profile, self.cfg, self.journal = profile, cfg, journal
        self.own_shared = shared is None
        self.shared = shared or SharedData(symbols, news, None)
        self.sink = sink or (lambda *a, **k: None)
        self.sim = Sim({}, replace(cfg), profile)
        self.sim.sig = {}
        self.paused, self.pause_reason, self.status = False, "", "attente"
        self.last_signal = None
        self.ctx: dict[str, Ctx] = {}

    def on_m5(self, sym, t_ns, bar):
        """Mode autonome (tests) : l'agent possède ses données."""
        if self.shared.add(sym, t_ns, bar):
            self.on_m15(sym)
            return True
        return False

    def on_m15(self, sym):
        ctx = self.shared.ctx(sym)
        if ctx is None:
            return
        self.ctx[sym] = ctx
        sig = ALGOS[self.algo].generate(ctx, self.params, EXIT_VARIANTS[self.exit_name])
        self.sim.mk[sym] = ctx.mk
        self.sim.sig[sym] = [sig]
        if self.paused:
            self.status = f"en pause : {self.pause_reason}"
            return
        n_ev, n_tr = len(self.sim.events), len(self.sim.trades)
        self.sim.process_bar(sym, ctx.n - 1)
        for ev in self.sim.events[n_ev:]:
            self.sink(self.name, sym, ev)
            if self.journal:
                self.journal.decision(ev.get("t", 0), self.name, sym, ev["type"], ev)
            if ev["type"] == "signal":
                self.last_signal = ev
        for tr in self.sim.trades[n_tr:]:
            if self.journal:
                self.journal.trade(self.name, tr)
        g = self.sim.g
        self.status = ("bloqué : " + g.reason) if (g.blocked_day or g.blocked_all) else \
            ("verrou de gain : plus d'entrée aujourd'hui" if g.blocked_gain and not self.sim.pos else
             "en position" if self.sim.pos else "attente")

    def trades_df(self):
        return pd.DataFrame(self.sim.trades)
