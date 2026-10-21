import numpy as np
import pandas as pd
from dataclasses import replace
from ftmo_algo.instruments import SPECS
from ftmo_algo.engine.market import build_market
from ftmo_algo.engine.news import NewsCalendar
from ftmo_algo.engine.sim import Sim, SimConfig
from ftmo_algo.algos.base import Signals, ExitCfg

ZERO = replace(SPECS["US500"], name="TEST", max_lot=1e6, spread=0.0, slippage=0.0, commission_lot=0.0, swap_long=0, swap_short=0)
COSTLY = replace(SPECS["US500"], name="TEST", max_lot=1e6, spread=0.5, slippage=0.2, commission_lot=0.2)


def bars(rows, start="2024-01-08 10:00", freq="15min"):
    idx = pd.date_range(start, periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 100
    return df


def market(rows, spec=ZERO):
    return build_market("TEST", bars(rows), spec, NewsCalendar(np.array([], dtype="int64")))


def signal(mk, i, side, stop, target, ex=None, grade=2):
    n = mk.n
    s = Signals("t", "TEST", np.zeros(n, np.int8), np.full(n, np.nan), np.full(n, np.nan), np.zeros(n, np.int8),
                ex or ExitCfg(rr=3, time_stop=0), max_per_day=5)
    s.side[i] = side; s.stop[i] = stop; s.target[i] = target; s.grade[i] = grade
    return s


def run(mk, sig, **cfg):
    c = SimConfig(min_rr_net=0.0, use_guardian=False, **cfg)
    sim = Sim({"TEST": mk}, c)
    return sim.run([sig])
