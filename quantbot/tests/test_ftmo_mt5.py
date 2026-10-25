from types import SimpleNamespace as NS

import pandas as pd
import pytest

from quantbot.config import Settings
from tests.synthetic import generate_synthetic
from quantbot.exceptions import ConfigError, ExecutionError, LiveTradingDisabledError
from quantbot.execution.broker import make_broker
from quantbot.memory.store import ExperimentStore
from quantbot.core.sim import TradingEngine
from quantbot.risk.ftmo import FtmoGuard
from quantbot.risk.manager import TradePlan

F = Settings().ftmo
T0 = pd.Timestamp("2024-03-05 10:00", tz="UTC")  # mardi


def guard(**kw):
    return FtmoGuard(Settings.from_dict({"ftmo": {"enabled": True, **kw}}).ftmo)


# --- règles FTMO ----------------------------------------------------------------
def test_defaults_match_ftmo_2step_100k():
    assert (F.initial_balance, F.max_daily_loss, F.max_total_loss) == (100_000, 0.05, 0.10)
    assert (F.profit_target_challenge, F.profit_target_verification, F.min_trading_days) == (0.10, 0.05, 4)


def test_ok_when_flat_and_healthy():
    st = guard().update(T0, 100_000, 100_000)
    assert not (st.halt_new or st.flatten or st.breached)
    assert st.total_floor == 92_000 and st.daily_floor == 96_000  # tampons internes 8 % / 4 %


def test_daily_buffer_flattens_before_hard_limit():
    g = guard()
    g.update(T0, 100_000, 100_000)
    st = g.update(T0 + pd.Timedelta(hours=1), 100_000, 95_900)  # -4.1 % flottant : sous le tampon, au-dessus de -5 %
    assert st.flatten and st.halt_new and not st.breached and "tampon_perte_journaliere" in st.reasons


def test_daily_hard_breach_is_permanent():
    g = guard()
    g.update(T0, 100_000, 100_000)
    assert g.update(T0 + pd.Timedelta(hours=1), 100_000, 94_900).breached
    assert g.update(T0 + pd.Timedelta(hours=2), 100_000, 100_000).breached  # même si ça remonte


def test_daily_reference_resets_at_prague_midnight():
    g = guard()
    g.update(pd.Timestamp("2024-03-05 22:30", tz="UTC"), 100_000, 100_000)  # 23:30 à Prague
    low = g.update(pd.Timestamp("2024-03-05 22:45", tz="UTC"), 100_000, 96_500)
    assert not low.halt_new and low.daily_floor == 96_000  # -3,5 % : au-dessus du tampon de 4 %
    nxt = g.update(pd.Timestamp("2024-03-05 23:30", tz="UTC"), 96_500, 96_500)  # 00:30 à Prague : nouveau jour
    assert not nxt.halt_new and nxt.daily_floor == pytest.approx(96_500 - 4_000)  # référence recalculée


def test_total_loss_static_floor():
    g = guard()
    st = g.update(T0, 91_900, 91_900)  # sous le tampon total (8 %)
    assert st.flatten and "tampon_perte_totale" in st.reasons
    assert guard().update(T0, 90_000, 89_999).breached


def test_weekend_and_news_blackouts():
    g = guard(news_blackouts=[["2024-03-06T13:25:00+00:00", "2024-03-06T13:45:00+00:00"]])
    fri = g.update(pd.Timestamp("2024-03-08 19:30", tz="UTC"), 100_000, 100_000)  # 20:30 Prague, vendredi
    assert fri.flatten and "weekend" in fri.reasons
    assert not g.update(pd.Timestamp("2024-03-08 18:30", tz="UTC"), 100_000, 100_000).flatten
    news = g.update(pd.Timestamp("2024-03-06 13:30", tz="UTC"), 100_000, 100_000)
    assert news.halt_new and not news.flatten
    assert not guard(flat_before_weekend=False).update(pd.Timestamp("2024-03-09 12:00", tz="UTC"), 1e5, 1e5).flatten


def test_target_requires_min_trading_days():
    g = guard()
    st = g.update(T0, 110_500, 110_500)
    assert not st.target_reached  # 0 jour de trading
    for d in range(4):
        g.register_trade_day(T0 + pd.Timedelta(days=d))
    st = g.update(T0 + pd.Timedelta(days=4), 110_500, 110_500)
    assert st.target_reached and st.halt_new and "objectif_atteint" in st.reasons
    ver = guard(phase="verification")
    assert ver.target == 105_000


def test_allowed_risk_shrinks_near_limits():
    g = guard()
    st = g.update(T0, 100_000, 100_000)
    assert g.allowed_risk(100_000, st) == pytest.approx(500)  # 0,5 % du capital initial
    st = g.update(T0, 100_000, 96_200)  # 200 $ au-dessus du tampon journalier
    assert g.allowed_risk(96_200, st) == pytest.approx(0.9 * 200)


def test_ftmo_config_validation():
    for bad in ({"max_daily_loss": 0.2}, {"phase": "x"}, {"timezone": "Mars/Olympus"}, {"daily_loss_buffer": 0.06},
                {"news_blackouts": [["a"]]}, {"max_risk_per_trade": 0.5}):
        with pytest.raises(ConfigError):
            Settings.from_dict({"ftmo": bad})


# --- MT5 (faux terminal) ------------------------------------------------------------
# --- moteur + garde-fou ---------------------------------------------------------------
def ftmo_settings(**kw):
    return Settings.from_dict({"ftmo": {"enabled": True, "flat_before_weekend": False, **kw}})


def test_guard_flattens_when_gap_crosses_both_limits_in_one_bar():
    """Régression de l'audit : un gap franchissant limite jour ET plancher total doit tout bloquer d'un coup."""
    g = guard()
    g.update(T0, 96_000, 96_000)  # référence du jour : 96 000 -> tampon jour 92 000 ; tampon total 92 000
    st = g.update(T0 + pd.Timedelta(minutes=15), 96_000, 91_900)  # franchit les DEUX tampons, pas la limite dure
    assert st.flatten and st.halt_new and not st.breached
    assert "tampon_perte_journaliere" in st.reasons and "tampon_perte_totale" in st.reasons


def test_engine_with_ftmo_never_goes_below_floor_and_counts_trading_days():
    df = generate_synthetic(900, seed=4)
    eng = TradingEngine(ftmo_settings(initial_balance=100_000))
    eng.run_replay(df)
    eng.finish(df)
    assert min(eng.equity_v) > 90_000 and eng.guard.trading_days and not eng.last_status.breached


def test_engine_caps_each_trade_risk_with_ftmo_headroom():
    df = generate_synthetic(900, seed=6)
    s = ftmo_settings()
    eng = TradingEngine(s)
    seen = []
    orig = eng.risk.build_plan

    def spy(*a, **k):
        plan = orig(*a, **k)
        if plan:
            seen.append(plan.risk_amount)
        return plan

    eng.risk.build_plan = spy
    eng.run_replay(df)
    assert seen and max(seen) <= s.ftmo.max_risk_per_trade * s.ftmo.initial_balance + 1e-6


def test_engine_flat_before_weekend():
    df = generate_synthetic(900, seed=4, freq="1h")
    eng = TradingEngine(Settings.from_dict({"ftmo": {"enabled": True}}))
    eng.run_replay(df)
    for t in eng.broker.trades:
        exit_local = pd.Timestamp(t.exit_time).tz_localize("UTC").tz_convert("Europe/Prague")
        entry_local = pd.Timestamp(t.entry_time).tz_localize("UTC").tz_convert("Europe/Prague")
        crossed = entry_local.weekday() == 4 and exit_local.weekday() >= 5
        assert not (crossed and t.reason == "max_hold")


def test_make_broker_live_is_refused_and_points_to_the_live_runtime(monkeypatch):
    monkeypatch.setenv("QUANTBOT_ALLOW_LIVE", "1")
    s = Settings.from_dict({"execution": {"mode": "live", "allow_live": True}, "ftmo": {"enabled": True}})
    with pytest.raises(LiveTradingDisabledError, match="quantbot.live"):
        make_broker(1, s.execution, ftmo=s.ftmo)


def test_store_promote_only_validated():
    from quantbot.exceptions import MemoryStoreError
    st = ExperimentStore()
    st.add_experiment("v0", Settings(), "baseline")
    st.add_experiment("v1", Settings(), "rejected", "v0")
    st.add_experiment("v2", Settings().with_overrides({"tolerance.min_score": 0.7}), "improved", "v0")
    with pytest.raises(MemoryStoreError):
        st.promote("v1")
    with pytest.raises(MemoryStoreError):
        st.promote("v9")
    st.promote("v2")
    assert st.current()[0] == "v2"
