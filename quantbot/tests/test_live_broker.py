import pandas as pd
import pytest

from quantbot.config import Settings
from quantbot.exceptions import ExecutionError, LiveTradingDisabledError
from quantbot.live.killswitch import KillSwitch
from quantbot.live.mt5_exec import HardenedMT5Broker
from quantbot.live.state import StateStore
from quantbot.risk.manager import TradePlan
from tests.fake_mt5_live import FakeMT5Live

TS = pd.Timestamp("2025-06-02 10:00")
PLAN = TradePlan("long", 2000.0, 1990.0, 2020.0, 100.0, 1000.0, 2.0, 0.8, ["amd_long"], 1000.0)


def make(tmp_path=None, mt5=None, **kw):
    mt5 = mt5 or FakeMT5Live()
    state = StateStore()
    kill = KillSwitch(state, (tmp_path or __import__("pathlib").Path(".")) / "KILL_TEST_ABSENT")
    s = Settings.from_dict({"execution": {"mt5_symbol": "XAUUSD"}})
    return HardenedMT5Broker(s.execution, s.ftmo, mt5, state, kill, "amd", **kw), mt5, state, kill


def test_nominal_open_check_before_send_levels_comment_and_state(tmp_path):
    b, m, st, k = make(tmp_path)
    pos = b.open_position(PLAN, 2000.0, TS)
    assert len(m.checked) == 1 and len(m.sent) == 1                       # order_check AVANT order_send
    req = m.sent[0]
    assert req["sl"] == 1990.0 and req["tp"] == 2020.0 and req["magic"] == b.cfg.mt5_magic and req["comment"].startswith("qb:")
    iid = req["comment"][3:]
    assert st.intent(iid)["status"] == "CONFIRMED" and st.intent(iid)["ticket"] is not None
    assert pos.side == "long" and b.position is pos and not k.active()


@pytest.mark.parametrize("flags,expected", [(2, 1), (1, 0), (0, 2), (3, 1)])
def test_filling_mode_is_detected_not_hardcoded(tmp_path, flags, expected):
    b, m, *_ = make(tmp_path, FakeMT5Live(filling_mode=flags))
    b.open_position(PLAN, 2000.0, TS)
    assert m.sent[0]["type_filling"] == expected                           # IOC=1, FOK=0, RETURN=2


def test_order_check_refusal_means_no_order_send(tmp_path):
    m = FakeMT5Live(); m.check_script = [m.TRADE_RETCODE_NO_MONEY]
    b, _, st, _ = make(tmp_path, m)
    with pytest.raises(ExecutionError):
        b.open_position(PLAN, 2000.0, TS)
    assert m.sent == [] and b.position is None
    assert st.recent_intents(1)[0]["status"] == "REFUSED"


def test_requote_retries_with_same_intent_then_succeeds(tmp_path):
    m = FakeMT5Live(); m.send_script = [m.TRADE_RETCODE_REQUOTE, m.TRADE_RETCODE_PRICE_CHANGED, m.TRADE_RETCODE_DONE]
    b, _, st, _ = make(tmp_path, m)
    b.open_position(PLAN, 2000.0, TS)
    assert len(m.sent) == 3 and len({r["comment"] for r in m.sent}) == 1   # même intention, aucun doublon
    assert len(st.recent_intents(10)) == 1 and len(m.positions) == 1


def test_retries_are_bounded(tmp_path):
    m = FakeMT5Live(); m.send_script = [m.TRADE_RETCODE_REQUOTE] * 10
    b, *_ = make(tmp_path, m, max_retries=2)
    with pytest.raises(ExecutionError):
        b.open_position(PLAN, 2000.0, TS)
    assert len(m.sent) == 3 and m.positions == []


def test_ambiguous_response_never_resends_and_trips_the_kill_switch(tmp_path):
    m = FakeMT5Live(); m.send_script = ["NONE"]
    b, _, st, k = make(tmp_path, m)
    with pytest.raises(ExecutionError, match="INCONNU"):
        b.open_position(PLAN, 2000.0, TS)
    assert len(m.sent) == 1 and k.active() and st.unknown_intents()       # un seul envoi ; état INCONNU
    with pytest.raises(ExecutionError, match="coupe-circuit"):
        b.open_position(PLAN, 2000.0, TS)                                  # plus aucune entrée possible
    assert len(m.sent) == 1


def test_ambiguous_but_executed_is_found_by_reconciliation_without_resending(tmp_path):
    m = FakeMT5Live(); m.send_script = ["EXECUTED_BUT_NO_ANSWER"]
    b, _, st, k = make(tmp_path, m)
    pos = b.open_position(PLAN, 2000.0, TS)
    assert len(m.sent) == 1 and len(m.positions) == 1 and pos is b.position   # pas de doublon
    assert not st.unknown_intents() and k.active()                           # intention résolue, MAIS le coupe-circuit reste (humain)
    assert "RESTE actif" in st.recent_events(5)[0]["detail"]


def test_kill_file_blocks_entries_but_not_exits(tmp_path):
    b, m, st, k = make(tmp_path)
    b.open_position(PLAN, 2000.0, TS)
    (tmp_path / "KILL_TEST_ABSENT").write_text("stop")
    assert k.active()
    b2 = b
    t = b2.close_position(2005.0, TS, "ftmo_guard")                          # sortir reste permis
    assert t.reason == "ftmo_guard" and b2.position is None
    with pytest.raises(ExecutionError, match="coupe-circuit"):
        b2.open_position(PLAN, 2000.0, TS)


def test_lots_below_minimum_and_missing_stop_never_reach_the_server(tmp_path):
    b, m, st, _ = make(tmp_path, FakeMT5Live(volume_min=5.0))
    with pytest.raises(ExecutionError, match="volume minimum"):
        b.open_position(PLAN, 2000.0, TS)
    assert m.checked == [] and m.sent == []
    b2, m2, *_ = make(tmp_path)
    bad = TradePlan("long", 2000.0, 0.0, 2020.0, 100.0, 1000.0, 2.0, 0.8, [], 1000.0)
    with pytest.raises(ExecutionError, match="obligatoires"):
        b2.open_position(bad, 2000.0, TS)
    assert m2.sent == []


def test_non_demo_account_refused_unless_every_lock_is_open(tmp_path, monkeypatch):
    real = FakeMT5Live(demo=False)
    with pytest.raises(LiveTradingDisabledError):
        make(tmp_path, real)
    monkeypatch.setenv("QUANTBOT_ALLOW_LIVE", "1")
    s = Settings.from_dict({"execution": {"mt5_symbol": "XAUUSD", "allow_live": True}, "ftmo": {"enabled": True}})
    with pytest.raises(LiveTradingDisabledError):                              # allow_real manquant
        HardenedMT5Broker(s.execution, s.ftmo, real, StateStore(), KillSwitch(StateStore(), tmp_path / "K"))
    ok = HardenedMT5Broker(s.execution, s.ftmo, real, StateStore(), KillSwitch(StateStore(), tmp_path / "K"), allow_real=True)
    assert not ok.demo


def test_server_allowlist_and_expected_login(tmp_path):
    with pytest.raises(ExecutionError, match="liste blanche"):
        make(tmp_path, FakeMT5Live(server="Evil-Live"), allowed_servers=("MetaQuotes-Demo",))
    s = Settings.from_dict({"execution": {"mt5_symbol": "XAUUSD"}, "ftmo": {"expected_login": 999}})
    with pytest.raises(ExecutionError, match="attendu"):
        HardenedMT5Broker(s.execution, s.ftmo, FakeMT5Live(login=1234), StateStore(), KillSwitch(StateStore(), tmp_path / "K"))


def test_server_side_exit_is_detected_and_pnl_comes_from_deals(tmp_path):
    b, m, *_ = make(tmp_path)
    b.open_position(PLAN, 2000.0, TS)
    assert b.sync(TS) is None                                                # toujours ouverte
    m.server_side_exit(2020.0)
    t = b.sync(TS + pd.Timedelta(minutes=15))
    assert t.reason == "server_exit" and t.pnl > 0 and b.position is None


def test_restore_adopts_known_position_and_flags_orphans(tmp_path):
    b, m, st, k = make(tmp_path)
    b.open_position(PLAN, 2000.0, TS)
    b2 = HardenedMT5Broker(Settings.from_dict({"execution": {"mt5_symbol": "XAUUSD"}}).execution, Settings().ftmo, m, st, k, "amd")
    adopted = b2.restore(engine_n=500)
    assert adopted is not None and adopted.entry_idx == 500 and adopted.side == "long"   # reprise sans doublon
    st2 = StateStore()                                                       # état vierge : la même position devient ORPHELINE
    k2 = KillSwitch(st2, tmp_path / "K2")
    b3 = HardenedMT5Broker(Settings.from_dict({"execution": {"mt5_symbol": "XAUUSD"}}).execution, Settings().ftmo, m, st2, k2)
    with pytest.raises(ExecutionError, match="orpheline"):
        b3.restore(1)
    assert k2.active()


def test_kill_switch_clear_requires_explicit_human_confirmation():
    st = StateStore(); k = KillSwitch(st, "KILL_NOPE")
    k.trigger("test")
    assert k.active()
    with pytest.raises(PermissionError):
        k.clear("oui")
    k.clear("JE_COMPRENDS")
    assert not k.active()
