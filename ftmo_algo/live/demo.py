"""Boucle démo MT5 : mêmes agents que le paper, ordres réels sur compte DÉMO avec SL/TP côté courtier."""
from __future__ import annotations
import math
import time
from pathlib import Path
from ..algos.library import BASE_ALGOS
from ..engine.guardian import PropProfile
from ..engine.news import NewsCalendar
from ..engine.sim import SimConfig
from ..instruments import SPECS, value_per_unit
from .agent import Agent, SharedData
from .feed import MT5Feed
from .journal import Journal
from .mt5_bridge import MT5Bridge
from .runner import Runner


def lots_for(spec, balance, risk_pct, entry, stop):
    per_lot = abs(entry - stop) * value_per_unit(spec, entry) + spec.commission_lot
    lots = math.floor(balance * risk_pct / 100 / per_lot / spec.lot_step) * spec.lot_step
    return round(min(max(lots, 0), spec.max_lot), 8)


def run_demo(a):
    import MetaTrader5 as mt5
    prof = PropProfile.load(a.profile)
    syms = [s.strip() for s in a.instruments.split(",")]
    bridge = MT5Bridge()
    journal = Journal(a.journal)
    Path(a.journal).parent.mkdir(exist_ok=True)
    now = mt5.symbol_info_tick(syms[0]).time
    news = NewsCalendar.default(__import__("pandas").Timestamp.utcnow() - __import__("pandas").Timedelta(days=60),
                                __import__("pandas").Timestamp.utcnow() + __import__("pandas").Timedelta(days=60))
    shared = SharedData(syms, news)
    from ..data.loaders import load_mt5
    import pandas as pd
    end = pd.Timestamp.utcnow(); start = end - pd.Timedelta(days=45)
    for s in syms:
        shared.preload(s, load_mt5(s, start, end, "M5"))
    cfg = SimConfig(risk_pct=a.risk, initial_balance=prof.initial_balance)
    agents = [Agent(n, n, None, syms, prof, cfg, news, journal, shared) for n in BASE_ALGOS]
    feed = MT5Feed(syms); feed.connect()
    runner = Runner(agents, feed, journal, "DÉMO", 0, news=news, profile=prof, shared=shared)
    orig = runner._sink

    def sink(agent, sym, ev):
        orig(agent, sym, ev)
        if ev["type"] == "signal":
            spec = SPECS[sym]
            lots = lots_for(spec, mt5.account_info().balance, a.risk, ev["ref"], ev["stop"])
            tp = ev["target"] if ev["target"] == ev["target"] else ev["ref"] + ev["side"] * 3 * abs(ev["ref"] - ev["stop"])
            if lots >= spec.min_lot:
                f = bridge.send_entry(sym, ev["side"], lots, ev["stop"], tp, ev["ref"], agent)
                journal.fill(time.time_ns(), agent, sym, f["requested"], f["executed"], "ok" if f["ok"] else "rejeté")
                if bridge.abnormal(spec.slippage):
                    for ag in agents:
                        ag.paused, ag.pause_reason = True, "écart d'exécution anormal"
    for ag in agents:
        ag.sink = sink
    t_end = time.time() + a.minutes * 60
    while time.time() < t_end:
        runner.step()
    print(bridge.reconcile([], None))
