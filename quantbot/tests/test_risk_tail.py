"""Régression de l'audit baseline_v0 : un stop quasi nul dans un marché vide transformait un gap en perte de milliers de R."""
import numpy as np
import pandas as pd
import pytest

from quantbot.config import Settings
from quantbot.execution.broker import PaperBroker
from quantbot.lab.gates import GateCfg, run_gates
from quantbot.patterns.base import PatternMatch
from quantbot.risk.manager import RiskManager
from quantbot.signals.engine import Signal, SignalEngine
from tests.helpers import frame


def _signal(atr, price=21000.0, direction="bearish"):
    m = PatternMatch("x", "candle", direction, 0.9, 0, 1)
    return Signal(direction, 0.9, price, atr, pd.Timestamp("2025-01-03 00:45"), [m])


def test_nominal_risk_is_the_unit_even_when_leverage_caps_the_size():
    s = Settings.from_dict({"risk": {"risk_per_trade": 0.005, "max_leverage": 3.0}})
    plan = RiskManager(s.risk).build_plan(_signal(atr=0.14), 100_000)  # stop ridicule : 0,2 point
    assert plan.size * plan.entry <= 100_000 * 3.0 + 1e-6  # notionnel plafonné
    assert plan.risk_amount < 10 and plan.nominal_risk == pytest.approx(500.0)  # risque planifié minuscule, nominal inchangé
    broker = PaperBroker(100_000, s.execution)
    broker.open_position(plan, 21000.0, pd.Timestamp("2025-01-03 00:45"))
    t = broker.close_position(21296.5, pd.Timestamp("2025-01-03 06:00"), "stop_gap")  # gap de +1,4 % contre un short
    assert t.r < -1000  # l'ancienne unité explose...
    assert -20 < t.r_nominal < -5  # ...l'unité nominale reste lisible : ~ -8 R nominaux = ~ -4 % du capital
    assert t.pnl == pytest.approx(t.r_nominal * 500.0)


def test_leverage_one_bounds_the_gap_loss():
    s = Settings.from_dict({"risk": {"risk_per_trade": 0.005, "max_leverage": 1.0}})
    plan = RiskManager(s.risk).build_plan(_signal(atr=0.14), 100_000)
    broker = PaperBroker(100_000, s.execution)
    broker.open_position(plan, 21000.0, pd.Timestamp("2025-01-03 00:45"))
    t = broker.close_position(21296.5, pd.Timestamp("2025-01-03 06:00"), "stop_gap")
    assert t.pnl > -0.02 * 100_000  # un gap de 1,4 % coûte ~1,4 % du capital, pas 4 %


def test_atr_floor_keeps_stop_sane_in_thin_market():
    rng = np.random.default_rng(0)
    rows, p = [], 100.0
    for i in range(300):
        rng_bar = 1.0 if i < 270 else 0.01  # 270 barres normales puis marché mince
        o = p; c = p + rng.normal(0, rng_bar * 0.3); rows.append((o, max(o, c) + rng_bar / 2, min(o, c) - rng_bar / 2, c)); p = c
    df = frame(rows)
    m = PatternMatch("x", "candle", "bullish", 0.9, 0, 1)
    plain = SignalEngine(Settings())
    plain.scanner.scan(df)
    floored = SignalEngine(Settings.from_dict({"signals": {"atr_floor_frac": 0.5}}))
    floored.scanner.scan(df)
    a0 = plain.build_signal(df, [m]).atr
    a1 = floored.build_signal(df, [m]).atr
    assert a0 < 0.2 and a1 >= 0.5 * np.nanmedian(floored.scanner.last_context.atr[-200:]) - 1e-9 and a1 > 3 * a0
    with pytest.raises(Exception):
        Settings.from_dict({"signals": {"atr_floor_frac": 5}})


def test_worst_trade_gate_fails_on_one_catastrophic_loss():
    rng = np.random.default_rng(1)
    r = rng.normal(0.3, 1.0, 300)
    ok = run_gates(r, r * 0.9, [0.1, 0.2, 0.1, 0.3], 1, 0.0, 3.0, 0.5, 10.0, GateCfg())
    bad_r = r.copy(); bad_r[7] = -80.0
    bad = run_gates(bad_r, bad_r * 0.9, [0.1, 0.2, 0.1, 0.3], 1, 0.0, 3.0, 0.5, 10.0, GateCfg())
    g = lambda gates: next(x for x in gates if x.name == "worst_trade")
    assert g(ok).ok and not g(bad).ok and g(bad).eliminatory


def test_weekend_blackout_calendar():
    from quantbot.risk.calendar import in_weekend_blackout as w
    assert not w("2025-04-04 17:00")          # vendredi 19:00 Prague (été) : encore ouvert
    assert w("2025-04-04 18:15")              # vendredi 20:15 Prague : fermeture
    assert w("2025-04-06 21:00") and w("2025-04-05 10:00")  # dimanche soir, samedi
    assert not w("2025-04-07 08:00")          # lundi


def test_engine_flattens_before_weekend_and_never_holds_over_it():
    from quantbot.core.sim import TradingEngine
    from tests.helpers import OracleSignals, planted_frame
    df = planted_frame(2500, seed=3)
    df.index = pd.date_range("2024-01-01", periods=len(df), freq="4h")
    s = Settings.from_dict({"risk": {"flat_before_weekend": True}})
    eng = TradingEngine(s, signal_engine=OracleSignals())
    eng.run_replay(df)
    eng.finish(df)
    from quantbot.risk.calendar import in_weekend_blackout as w
    assert eng.broker.trades
    assert all(not w(t.entry_time) for t in eng.broker.trades)  # aucune entrée en fenêtre de week-end
    assert any(t.reason == "weekend" for t in eng.broker.trades)  # des positions ont bien été fermées avant
    cross = [t for t in eng.broker.trades if t.entry_time.weekday() < 5 and t.exit_time.weekday() >= 5 and t.reason != "weekend"
             and not (t.exit_time.weekday() == 5 and t.exit_time.hour < 12)]
    assert not cross
