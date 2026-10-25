import numpy as np
import pandas as pd
import pytest

from quantbot.backtest.engine import Backtester
from quantbot.config import Settings
from tests.synthetic import generate_synthetic
from quantbot.exceptions import ExecutionError, LiveTradingDisabledError
from quantbot.execution.broker import PaperBroker, make_broker
from quantbot.patterns.base import PatternMatch
from quantbot.risk.manager import RiskManager, TradePlan, historical_var
from quantbot.signals.engine import Signal, SignalEngine
from tests.helpers import bar, downtrend, frame, from_waypoints

S = Settings()


def match(name="hammer", direction="bullish", score=0.9, cat="candle", confirmed=True):
    return PatternMatch(name, cat, direction, score, 0, 1, confirmed)


# --- signaux ---------------------------------------------------------------
def test_signal_direction_and_confluence():
    df = frame(downtrend() + [bar(99.8, 100.2, h=100.4, l=97.0)])
    eng = SignalEngine(S)
    one = eng.build_signal(df, [match()])
    two = eng.build_signal(df, [match(), match("double_bottom", cat="chart")])
    assert one.direction == "bullish" and two.confidence > one.confidence


def test_signal_ambiguous_returns_none():
    eng = SignalEngine(S)
    df = frame(downtrend() + [bar(99.8, 100.2)])
    assert eng.build_signal(df, [match(score=0.9), match("x", "bearish", 0.88)]) is None
    assert eng.build_signal(df, []) is None


def test_unconfirmed_penalty_and_requirement():
    df = frame(downtrend() + [bar(99.8, 100.2)])
    eng = SignalEngine(S)
    full = eng.build_signal(df, [match(cat="chart", confirmed=True)]).confidence
    pen = eng.build_signal(df, [match(cat="chart", confirmed=False)]).confidence
    assert pen == pytest.approx(full * S.signals.unconfirmed_penalty)
    strict = SignalEngine(Settings.from_dict({"signals": {"require_confirmation": True}}))
    assert strict.build_signal(df, [match(cat="chart", confirmed=False)]) is None


def test_counter_trend_penalty():
    eng = SignalEngine(Settings.from_dict({"signals": {"trend_filter": "ema", "min_confidence": 0.1}}))
    df = frame(downtrend(80) + [bar(50, 50.4)])  # tendance baissière
    sig = eng.build_signal(df, [match()])
    base = SignalEngine(Settings.from_dict({"signals": {"min_confidence": 0.1}})).build_signal(df, [match()])
    assert sig.confidence < base.confidence and sig.notes


def test_signal_end_to_end_on_pattern_data():
    df = frame(from_waypoints([100, 200, 138.2, 176.4, 121.4]))
    sig = SignalEngine(S).evaluate(df)
    assert sig is not None and sig.direction == "bullish" and "gartley" in sig.pattern_names


# --- risque ----------------------------------------------------------------
def signal(direction="bullish", atr=2.0, price=100.0):
    return Signal(direction, 0.8, price, atr, pd.Timestamp("2024-01-01"), [match()])


def test_plan_long_short_geometry():
    rm = RiskManager(S.risk)
    p = rm.build_plan(signal(), 10_000)
    assert p.stop == pytest.approx(97.0) and p.take_profit == pytest.approx(106.0)
    assert p.risk_amount == pytest.approx(100.0)  # 1% de 10 000
    q = rm.build_plan(signal("bearish"), 10_000)
    assert q.side == "short" and q.stop > q.entry > q.take_profit


def test_plan_leverage_cap_and_rejections():
    rm = RiskManager(S.risk)
    p = rm.build_plan(signal(atr=0.01), 10_000)  # stop minuscule -> taille plafonnée
    assert p.size * p.entry <= 10_000 * S.risk.max_leverage + 1e-6
    assert rm.build_plan(signal(atr=float("nan")), 10_000) is None and rm.last_rejection == "atr_invalide"
    assert rm.build_plan(signal(atr=70.0), 10_000) is None and rm.last_rejection == "stop_negatif"
    assert rm.build_plan(signal(), 0) is None


def test_daily_limits():
    cfg = Settings.from_dict({"risk": {"max_trades_per_day": 2, "max_daily_loss": 0.02}}).risk
    rm = RiskManager(cfg)
    t = pd.Timestamp("2024-03-01 10:00")
    assert rm.can_trade(t, 10_000)[0]
    rm.register_open(t, 10_000); rm.register_open(t, 10_000)
    assert rm.can_trade(t, 10_000) == (False, "max_trades_per_day")
    assert rm.can_trade(t + pd.Timedelta(days=1), 10_000)[0]  # nouveau jour
    rm2 = RiskManager(cfg)
    rm2.can_trade(t, 10_000); rm2.register_close(t, -250, 9_750)
    assert rm2.can_trade(t, 9_750) == (False, "max_daily_loss")


def test_var():
    assert historical_var(np.array([])) == 0.0
    assert historical_var(np.linspace(-0.1, 0.1, 201), 0.95) == pytest.approx(0.09, abs=0.005)


# --- exécution --------------------------------------------------------------
def plan(side="long"):
    return TradePlan(side, 100, 97 if side == "long" else 103, 106 if side == "long" else 94, 10, 30, 2, 0.8, ["x"])


def test_paper_broker_pnl_costs_and_errors():
    cfg = Settings.from_dict({"execution": {"fee_rate": 0.001, "slippage": 0.0}}).execution
    b = PaperBroker(10_000, cfg)
    b.open_position(plan(), 100, pd.Timestamp("2024-01-01"))
    with pytest.raises(ExecutionError):
        b.open_position(plan(), 100, pd.Timestamp("2024-01-01"))
    t = b.close_position(106, pd.Timestamp("2024-01-02"), "take_profit", market=False)
    assert t.pnl == pytest.approx(60 - 1.0 - 1.06)
    assert b.equity() == pytest.approx(10_000 + t.pnl)
    with pytest.raises(ExecutionError):
        b.close_position(100, pd.Timestamp("2024-01-02"), "x")


def test_short_pnl_and_slippage_hurts():
    free = PaperBroker(10_000, Settings.from_dict({"execution": {"fee_rate": 0, "slippage": 0}}).execution)
    slip = PaperBroker(10_000, Settings.from_dict({"execution": {"fee_rate": 0, "slippage": 0.01}}).execution)
    for b in (free, slip):
        b.open_position(plan("short"), 100, pd.Timestamp("2024-01-01"))
    a = free.close_position(94, pd.Timestamp("2024-01-02"), "tp", market=False).pnl
    c = slip.close_position(94, pd.Timestamp("2024-01-02"), "tp", market=False).pnl
    assert a == pytest.approx(60) and c < a


def test_live_needs_every_lock(monkeypatch):
    live = Settings.from_dict({"execution": {"mode": "live"}})
    with pytest.raises(LiveTradingDisabledError):
        make_broker(1000, live.execution, ftmo=live.ftmo)
    allowed = Settings.from_dict({"execution": {"mode": "live", "allow_live": True}})
    with pytest.raises(LiveTradingDisabledError):  # config seule ne suffit pas
        make_broker(1000, allowed.execution, ftmo=allowed.ftmo)
    monkeypatch.setenv("QUANTBOT_ALLOW_LIVE", "1")
    with pytest.raises(LiveTradingDisabledError):  # garde-fou FTMO obligatoire
        make_broker(1000, allowed.execution, ftmo=allowed.ftmo)


# --- backtest ---------------------------------------------------------------
def test_backtest_runs_and_is_deterministic():
    df = generate_synthetic(700, seed=3)
    r1, r2 = Backtester(S).run(df), Backtester(S).run(df)
    assert r1.metrics == r2.metrics and r1.metrics["n_trades"] > 0
    assert all(t.exit_time >= t.entry_time for t in r1.trades)
    assert r1.equity_curve.notna().all()


def test_backtest_no_lookahead():
    """Modifier le futur ne doit pas changer les trades déjà clôturés avant."""
    df = generate_synthetic(700, seed=5)
    cut = 500
    altered = df.copy()
    altered.iloc[cut:, :4] = altered.iloc[cut:, :4].to_numpy() * 1.5
    a = Backtester(S).run(df).trades
    b = Backtester(S).run(altered).trades
    pa = [(t.entry_time, t.exit_time, round(t.pnl, 6)) for t in a if t.exit_time < df.index[cut - 1]]
    pb = [(t.entry_time, t.exit_time, round(t.pnl, 6)) for t in b if t.exit_time < df.index[cut - 1]]
    assert pa == pb and pa


def test_higher_costs_lower_return():
    df = generate_synthetic(700, seed=3)
    cheap = Backtester(S, 1.0).run(df).metrics["total_return"]
    pricey = Backtester(S, 5.0).run(df).metrics["total_return"]
    assert pricey < cheap


def test_stop_and_target_priority():
    pos = type("P", (), dict(side="long", stop=95.0, take_profit=105.0))()
    assert Backtester._check_exit(pos, 100, 106, 94, 100, 1, 50)[1] == "stop_loss"  # SL prime
    assert Backtester._check_exit(pos, 94, 99, 93, 96, 1, 50)[1] == "stop_gap"
    assert Backtester._check_exit(pos, 100, 101, 99, 100, 60, 50)[1] == "max_hold"
    assert Backtester._check_exit(pos, 100, 101, 99, 100, 1, 50) is None


def test_backtest_rejects_short_data():
    from quantbot.exceptions import DataValidationError
    with pytest.raises(DataValidationError):
        Backtester(S).run(generate_synthetic(60))
