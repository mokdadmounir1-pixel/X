"""Exécution multi-agents (rejeu ou direct), kill switches, notifications, état pour le dashboard."""
from __future__ import annotations
import json
import os
import threading
import time
import urllib.request
from collections import deque
import numpy as np
import pandas as pd
from ..algos.library import ALGOS
from ..instruments import SPECS


class Notifier:
    """Notifications : file lue par le navigateur (/api/state) + Telegram si configuré (variables d'env)."""

    def __init__(self):
        self.items = deque(maxlen=200)
        self.n = 0
        self.token, self.chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")

    def notify(self, kind, text, level="info"):
        self.n += 1
        self.items.append({"id": self.n, "kind": kind, "text": text, "level": level, "ts": time.time()})
        if self.token and self.chat:
            try:
                data = json.dumps({"chat_id": self.chat, "text": f"[{kind}] {text}"}).encode()
                req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/sendMessage", data,
                                             {"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass


class KillSwitch:
    def __init__(self, band: dict | None = None, exec_dev_mult=3.0):
        self.band = band or {}          # {agent: (r_values_ndarray)} distribution OOS pour l'intervalle attendu
        self.exec_dev_mult = exec_dev_mult
        self.slips = deque(maxlen=10)

    def expected_interval(self, agent, n, paths=1000, seed=0):
        r = self.band.get(agent)
        if r is None or len(r) < 10 or n < 1:
            return None
        rng = np.random.default_rng(seed)
        s = rng.choice(r, size=(paths, n)).sum(1)
        return float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5))

    def check(self, ag, journal_slips=None):
        g = ag.sim.g
        if g.blocked_all:
            return "limite du gardien atteinte (perte max interne)"
        tr = ag.sim.trades
        if len(tr) >= 20:
            iv = self.expected_interval(ag.name, len(tr))
            cum = sum(t["r"] for t in tr)
            if iv and cum < iv[0]:
                return f"performance live ({cum:.1f}R) sous l'intervalle Monte Carlo attendu ({iv[0]:.1f}R)"
        return None


class Runner:
    def __init__(self, agents, feed, journal=None, label="REPLAY", speed=0.0, notifier=None, kill=None, news=None,
                 profile=None, data_quality=None, tools_status=None, target_info=None, shared=None):
        self.agents, self.feed, self.journal = agents, feed, journal
        self.shared = shared
        self.label = label
        self.speed = speed
        self.notifier = notifier or Notifier()
        self.kill = kill or KillSwitch()
        self.news = news
        self.profile = profile
        self.paused = False
        self.stop = False
        self.tape = deque(maxlen=120)
        self.m15: dict[str, list] = {}
        self.now_ns = 0
        self.flux_ok = True
        self.data_quality = data_quality or []
        self.tools_status = tools_status or {}
        self.target_info = target_info or {}
        self.verdicts = {}
        self.lock = threading.RLock()
        self.bars = 0
        for a in agents:
            a.sink = self._sink

    def _sink(self, agent, sym, ev):
        t = ev.get("type")
        if t in ("open", "close", "partial", "guardian", "breach", "signal", "reject"):
            if t == "reject" and ev.get("why") not in ("rr_net", "lot_min", "annonce"):
                return
            self.tape.appendleft({"agent": agent, "sym": sym, **{k: (float(v) if isinstance(v, (np.floating, float)) else v)
                                                              for k, v in ev.items() if k != "feat"}, "wall": time.time()})
        if t == "open":
            self.notifier.notify("TRADE OUVERT", f"{agent} {sym} {'LONG' if ev['side']>0 else 'SHORT'} @ {ev['entry']:.5g} RR net {ev['rr_net']}")
        elif t == "close":
            self.notifier.notify("TRADE FERMÉ", f"{agent} {sym} {ev['reason']} {ev['r']:+.2f}R")
        elif t == "guardian":
            self.notifier.notify("LIMITE APPROCHÉE", f"{agent}: gardien {ev['action']}", "warn")

    def step(self):
        item = self.feed.next()
        if item is None:
            return False
        if item == "WAIT":
            if self.feed.stale():
                if self.flux_ok:
                    self.notifier.notify("FLUX COUPÉ", "aucune nouvelle barre reçue", "alert")
                self.flux_ok = False
                for a in self.agents:
                    a.paused, a.pause_reason = True, "flux interrompu"
            return True
        sym, t, bar = item
        self.flux_ok = True
        self.now_ns = t
        self.bars += 1
        with self.lock:
            done = self.shared.add(sym, t, bar)
            for a in self.agents:
                if sym in a.symbols and done:
                    a.on_m15(sym)
                    if not a.paused:
                        why = self.kill.check(a)
                        if why:
                            a.paused, a.pause_reason = True, why
                            self.notifier.notify("AGENT EN PAUSE", f"{a.name}: {why}", "alert")
        return True

    def run(self, max_bars=None):
        n = 0
        while not self.stop and (max_bars is None or n < max_bars):
            if self.paused:
                time.sleep(0.1); continue
            if not self.step():
                break
            n += 1
            if self.speed > 0:
                time.sleep(max(0.0, 0.02 / self.speed))
        return n

    # --------------------------------------------------------------- état pour le dashboard
    def state(self, sym_view: str | None = None, tf: str = "M15"):
        with self.lock:
            now = self.now_ns
            agents = []
            for a in self.agents:
                tr = a.trades_df()
                rs = tr.r.to_numpy() if len(tr) else np.array([])
                risk = a.cfg.risk_pct
                pos = [{"sym": p.sym, "side": p.side, "entry": p.entry, "stop": p.stop, "target": p.target,
                        "lots": p.lots, "grade": p.grade} for p in a.sim.pos]
                agents.append({"name": a.name, "algo": a.algo, "status": a.status, "paused": a.paused,
                               "n": int(len(rs)), "cum_R": round(float(rs.sum()), 2) if len(rs) else 0.0,
                               "pct": round(float(rs.sum()) * risk, 2) if len(rs) else 0.0,
                               "expectancy": round(float(rs.mean()), 3) if len(rs) else None,
                               "spark": [round(float(x), 2) for x in np.cumsum(rs)[-60:]] if len(rs) else [],
                               "setup": ({"grade": ("B", "A", "A+")[a.last_signal.get("grade", 0)], "side": a.last_signal.get("side")}
                                         if a.last_signal else None),
                               "positions": pos, "equity": round(a.sim.last_equity, 2),
                               "guardian": {"day_loss_pct": round((a.sim.g.day_ref - a.sim.last_equity) / a.profile.initial_balance * 100, 3),
                                            "limit_daily": a.profile.daily_loss_pct,
                                            "tot_loss_pct": round((a.profile.initial_balance - a.sim.last_equity) / a.profile.initial_balance * 100, 3),
                                            "limit_total": a.profile.max_loss_pct, "blocked": a.sim.g.blocked_day or a.sim.g.blocked_all}})
            sym = sym_view or (self.agents[0].symbols[0] if self.agents else None)
            candles, levels = [], []
            a0 = next((a for a in self.agents if sym in a.ctx), None)
            vortex = self._vortex(sym)
            if a0 is not None:
                c = a0.ctx[sym]
                k = max(0, c.n - 120)
                idx = c.df.index[k:]
                candles = [[int(t.timestamp()), float(o), float(h), float(l), float(cl)] for t, o, h, l, cl in
                           zip(idx, c.o[k:], c.h[k:], c.l[k:], c.c[k:])]
            for a in self.agents:
                for p in a.sim.pos:
                    if p.sym == sym:
                        rr = abs(p.target - p.entry) / max(p.r_dist, 1e-12)
                        levels.append({"agent": a.name, "side": p.side, "entry": p.entry, "stop": p.stop, "target": p.target,
                                       "rr": round(rr, 2)})
            tinfo = {}
            ti = self.target_info
            if ti and ti.get("risk_pct"):
                allr = [(t["exit_t"], t["r"]) for a in self.agents for t in a.sim.trades]
                mon = pd.Timestamp(now, tz="UTC").to_period("M") if now else None
                cur = sorted((e, r) for e, r in allr if mon is not None and pd.Timestamp(e, tz="UTC").to_period("M") == mon)
                rr = [r for _, r in cur]
                streak = 0
                for r in reversed(rr):
                    if r < 0:
                        streak += 1
                    else:
                        break
                tinfo = {**ti, "actual": [0.0] + [round(float(x), 3) for x in np.cumsum(rr)] if rr else [0.0],
                         "cum_R": round(float(sum(rr)), 2), "cum_pct": round(float(sum(rr)) * ti["risk_pct"], 2), "streak": streak}
            nxt = self.news.next_events(now, 4) if (self.news is not None and now) else []
            return {"label": self.label, "flux_ok": self.flux_ok, "paused": self.paused, "speed": self.speed, "bars": self.bars,
                    "now": now // 10**9 if now else 0, "symbol": sym, "agents": agents, "tape": list(self.tape)[:40],
                    "candles": candles, "levels": levels, "vortex": vortex, "news": [{"t": t // 10**9, "name": n} for t, n in nxt],
                    "symbols": sorted({x for a in self.agents for x in a.symbols}), "notifications": list(self.notifier.items)[-30:], "verdicts": self.verdicts,
                    "data_quality": self.data_quality, "tools": self.tools_status, "target": tinfo,
                    "profile": {"name": self.profile.name if self.profile else "", "daily": self.profile.daily_loss_pct if self.profile else 5,
                                "total": self.profile.max_loss_pct if self.profile else 10,
                                "verified": self.profile.verified_on if self.profile else ""}}

    def _vortex(self, sym):
        """Entrées du vortex : rotation = vol courte/longue ; étirement = force de tendance ; cohérence =
        accord entre agents ; couleur = direction ; nœuds = agents (allumés en position/signal)."""
        c = next((a.ctx[sym] for a in self.agents if sym in a.ctx), None)
        if c is None:
            return {"vol_ratio": 1.0, "trend": 0.0, "coherence": 0.0, "direction": 0, "nodes": []}
        i = c.n - 1
        s_atr = float(np.mean(c.atr[-8:])); l_atr = float(np.mean(c.atr[-96:]))
        dirs = []
        nodes = []
        for a in self.agents:
            d = 0
            if a.sim.pos:
                d = int(np.sign(sum(p.side for p in a.sim.pos)))
            elif a.last_signal and a.last_signal.get("t", 0) // 10**9 > (self.now_ns // 10**9) - 3600:
                d = int(a.last_signal.get("side", 0))
            dirs.append(d)
            nodes.append({"name": a.name, "lit": bool(a.sim.pos) or d != 0, "dir": d,
                          "pulse": bool(a.sim.events and a.sim.events[-1].get("type") in ("open", "close"))})
        act = [d for d in dirs if d != 0]
        coh = abs(sum(act)) / len(act) if act else 0.0
        direction = int(np.sign(c.c[-1] - c.ema50[-1]))
        return {"vol_ratio": round(s_atr / max(l_atr, 1e-12), 3), "trend": round(float(c.h1_adx[i]) / 50.0 if np.isfinite(c.h1_adx[i]) else 0.0, 3),
                "coherence": round(coh, 3), "direction": direction, "nodes": nodes}
