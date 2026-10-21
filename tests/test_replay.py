import numpy as np
import pandas as pd
import pytest
from ftmo_algo.algos.context import Ctx
from ftmo_algo.algos.library import ALGOS, EXIT_VARIANTS
from ftmo_algo.data.quality import resample_ohlc
from ftmo_algo.data.synth import make_series
from ftmo_algo.engine.guardian import PropProfile
from ftmo_algo.engine.news import NewsCalendar
from ftmo_algo.engine.sim import Sim, SimConfig
from ftmo_algo.live.agent import Agent, SharedData
from ftmo_algo.live.feed import ReplayFeed
from ftmo_algo.live.journal import Journal
from ftmo_algo.live.runner import Runner
from ftmo_algo.timeutil import ns


@pytest.mark.parametrize("algo", ["session_orb", "squeeze_breakout"])
def test_same_logic_backtest_paper_replay_identical_trades(algo):
    m5 = make_series("US500", years=0.2, seed=11)
    news = NewsCalendar.default(m5.index[0], m5.index[-1])
    prof = PropProfile(); cfg = dict(risk_pct=0.5, min_rr_net=1.0, grades=(2, 1, 0))
    cut = m5.index[-1] - pd.Timedelta(days=9)
    # --- backtest : signaux précalculés sur la série complète, démarrage à `cut`
    m15 = resample_ohlc(m5, "M15").drop(columns=["close_time"])
    ctx = Ctx("US500", m15, news=news)
    a = ALGOS[algo]
    sig = a.generate(ctx, a.default, EXIT_VARIANTS["fixed3"])
    sim = Sim({"US500": ctx.mk}, SimConfig(**cfg), prof)
    bt = sim.run([sig], t0=cut.value).trades
    # --- paper / rejeu : mêmes barres M5 une à une, mêmes agents, contexte reconstruit sur le préfixe
    shared = SharedData(["US500"], news, window_bars=None)
    shared.preload("US500", m5[m5.index < cut])
    ag = Agent("x", algo, None, ["US500"], prof, SimConfig(**cfg), news, Journal(), shared)
    r = Runner([ag], ReplayFeed({"US500": m5}, start=cut), label="REPLAY", profile=prof, news=news, shared=shared)
    r.run()
    ag.sim._close_all("fin_donnees")
    pp = ag.trades_df()
    cols = ["entry_t", "exit_t", "entry", "exit", "lots", "r"]
    # la dernière position encore ouverte est fermée « fin_donnees » des deux côtés
    assert len(bt) > 0, "le test doit produire des trades"
    assert len(bt) == len(pp)
    assert np.allclose(bt[cols].to_numpy("float64"), pp[cols].to_numpy("float64"), rtol=1e-9, atol=1e-9)
    # le journal SQLite contient chaque décision
    assert len(ag.journal.db.execute("SELECT * FROM decisions").fetchall()) > 0
