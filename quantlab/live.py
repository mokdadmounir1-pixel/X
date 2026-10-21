"""Paper-trading loop: every strategy is an 'agent' with its own account, fed bar by bar.
Source = replay of a DataFrame (synthetic or CSV) or live polling through ccxt."""
from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np
import pandas as pd

from .engine import EngineCfg
from .strategies import REGISTRY

WINDOW = 700


class Agent:
    def __init__(self, name, cfg: EngineCfg, params=None):
        self.name, self.cfg = name, cfg
        self.strat = REGISTRY[name](**(params or {}))
        self.eq = cfg.equity
        self.pos = 0
        self.trades = []
        self.curve = deque([cfg.equity], maxlen=80)
        self.last_side = 0
        self.pending = 0
        self.pending_sl = self.pending_tp = 0.0
        self.cool = 0
        self.conf = 0.0

    def on_bar(self, win: pd.DataFrame, events):
        c = self.cfg.costs
        bar = win.iloc[-1]
        t = win.index[-1]
        if self.pos:
            hold_exit = (len(win) - 1 - self.ent_i) >= self.hold
            hs = bar.low <= self.stop if self.pos > 0 else bar.high >= self.stop
            ht = bar.high >= self.tgt if self.pos > 0 else bar.low <= self.tgt
            ex = reason = None
            if hs:
                ex, reason = self.stop * (1 - self.pos * c.slip_pct / 100), "stop"
            elif ht:
                ex, reason = self.tgt, "target"
            elif hold_exit:
                ex, reason = bar.close, "time"
            if ex is not None:
                pnl = (ex - self.ent) * self.pos * self.qty - (self.ent + ex) * self.qty * c.fee_pct / 100
                self.eq += pnl
                tr = dict(time=str(t), agent=self.name, side=self.pos, entry=self.ent, exit=ex, pnl=pnl, reason=reason)
                self.trades.append(tr)
                events.append(dict(type="fill", **tr))
                self.pos, self.cool = 0, self.cfg.cooldown
        if self.pending and not self.pos and self.cool == 0:
            s = self.pending
            px = bar.open * (1 + s * (c.slip_pct + c.spread_pct / 2) / 100)
            risk = self.eq * self.cfg.risk_pct / 100
            self.qty = min(risk / self.pending_sl, self.eq * self.cfg.max_leverage / px)
            self.pos, self.ent, self.ent_i = s, px, len(win) - 1
            self.stop, self.tgt, self.hold = px - s * self.pending_sl, px + s * self.pending_tp, self.strat.p.get("max_hold", 30)
            events.append(dict(type="entry", time=str(t), agent=self.name, side=s, price=px))
        self.pending = 0
        if self.cool > 0:
            self.cool -= 1
        sg = self.strat.signals(win)
        self.last_side = int(sg.side[-1])
        if self.last_side and not self.pos and np.isfinite(sg.sl[-1]) and sg.sl[-1] > 0:
            self.pending, self.pending_sl, self.pending_tp = self.last_side, float(sg.sl[-1]), float(sg.tp[-1])
        mtm = self.eq + ((bar.close - self.ent) * self.pos * self.qty if self.pos else 0.0)
        self.curve.append(mtm)

    def stats(self):
        w = [t for t in self.trades if t["pnl"] > 0]
        return dict(name=self.name, desc=self.strat.desc, equity=self.curve[-1], pnl=self.curve[-1] - self.cfg.equity, trades=len(self.trades),
                    win_rate=(100 * len(w) / len(self.trades)) if self.trades else 0.0, pos=self.pos, signal=self.last_side,
                    spark=list(self.curve)[::2])


class LiveSession:
    def __init__(self, df: pd.DataFrame, names, cfg=None, params_by=None, speed=2.0, daily_target_pct=1.0, source="replay"):
        self.df, self.cfg, self.speed, self.source = df, cfg or EngineCfg(), speed, source
        self.agents = [Agent(n, self.cfg, (params_by or {}).get(n)) for n in names]
        self.i = WINDOW
        self.candles = deque(maxlen=120)
        self.tape = deque(maxlen=40)
        self.signals_seen = 0
        self.paused = False
        self.price = float(df.close.iloc[WINDOW])
        self.start = time.time()
        self.target = daily_target_pct
        self.cond = threading.Condition()
        self.subs: list = []
        self.vortex = dict(omega=1.0, stretch=1.0, coherence=0.0, vorticity=0.0, phase=0, regime="range")
        self.day_pnl_hist = deque(maxlen=200)
        for k in range(WINDOW - 120, WINDOW):
            r = df.iloc[k]
            self.candles.append(self._c(df.index[k], r))
        self.thread = threading.Thread(target=self._loop, daemon=True)

    @staticmethod
    def _c(t, r):
        return [int(t.timestamp()), float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume)]

    def emit(self, ev):
        for q in list(self.subs):
            q.append(ev)

    def _vortex_update(self, win):
        ret = np.log(win.close).diff().dropna().values
        short, long_ = ret[-20:].std() + 1e-12, ret[-200:].std() + 1e-12
        trend = abs(ret[-30:].sum()) / (ret[-30:].std() * np.sqrt(30) + 1e-12)
        sides = np.array([a.last_side for a in self.agents])
        act = sides[sides != 0]
        coh = abs(act.sum()) / len(act) if len(act) else 0.0
        self.vortex = dict(omega=float(np.clip(short / long_, 0.3, 3.5)), stretch=float(np.clip(trend, 0.2, 3)),
                           coherence=float(coh), vorticity=float(len(act) / max(1, len(sides))), net=float(sides.sum()),
                           regime="trend" if trend > 1.2 else "range", dir=float(np.sign(ret[-30:].sum())))

    def step(self):
        k = self.i
        win = self.df.iloc[max(0, k - WINDOW + 1):k + 1]
        events = []
        for a in self.agents:
            a.on_bar(win, events)
        self.signals_seen += sum(1 for a in self.agents if a.last_side)
        row = self.df.iloc[k]
        self.candles.append(self._c(self.df.index[k], row))
        self.price = float(row.close)
        self._vortex_update(win)
        for e in events:
            self.tape.appendleft(e)
        self.emit(dict(type="bar", candle=self.candles[-1], vortex=self.vortex))
        self.i = k + 1 if k + 1 < len(self.df) else WINDOW

    def _loop(self):
        while True:
            if not self.paused:
                self.step()
            time.sleep(max(0.02, 1.0 / max(self.speed, 0.05)))

    def snapshot(self):
        ag = [a.stats() for a in self.agents]
        pnl = sum(a["pnl"] for a in ag)
        n = sum(a["trades"] for a in ag)
        wins = sum(a["win_rate"] / 100 * a["trades"] for a in ag)
        return dict(sim=self.source == "replay", source=self.source, price=self.price, candles=list(self.candles), vortex=self.vortex,
                    balance=self.cfg.equity * len(ag) + pnl, capital=self.cfg.equity * len(ag), pnl=pnl, trades=n,
                    win_rate=(100 * wins / n) if n else 0.0, signals=self.signals_seen, agents=ag, tape=list(self.tape),
                    target_pct=self.target, speed=self.speed, paused=self.paused, uptime=int(time.time() - self.start))
