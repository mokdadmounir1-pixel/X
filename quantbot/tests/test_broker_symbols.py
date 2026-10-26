import importlib.util, json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from quantbot.live.symbols import AliasMT5, candidates, maybe_alias, resolve
from tests.fake_mt5_live import FakeMT5Live

S = importlib.util.spec_from_file_location("broker_profile", Path(__file__).resolve().parents[1] / "scripts" / "broker_profile.py"); bp = importlib.util.module_from_spec(S); S.loader.exec_module(bp)


class GoldBroker(FakeMT5Live):
    """Courtier dont l'or s'appelle GOLD.a et l'indice NAS100.a ; toute requête sur un nom canonique échoue."""
    NAMES = {"GOLD.a", "EURUSD.a", "NAS100.a"}
    def __init__(self, **kw): super().__init__(**kw); self.seen = []; self.info.trade_tick_size = 0.01; self.info.trade_contract_size = 100
    def symbols_get(self): return [NS(name=n) for n in sorted(self.NAMES)]
    def symbol_info(self, s): self.seen.append(s); return self.info if s in self.NAMES else None
    def symbol_select(self, s, e): return s in self.NAMES
    def symbol_info_tick(self, s): return NS(bid=2000.0, ask=2000.08, time=0) if s in self.NAMES else None
    def terminal_info(self): return NS(connected=True, company="TestBroker")


def test_candidates_and_resolve_finds_gold_and_nasdaq_aliases_and_reports_missing():
    m = GoldBroker(); assert "GOLD.a" in candidates("XAUUSD")
    r = resolve(m, "XAUUSD"); assert r["broker"] == "GOLD.a" and r["status"] == "alias"
    assert resolve(m, "USTEC")["broker"] == "NAS100.a" and resolve(m, "EURUSD")["broker"] == "EURUSD.a"
    miss = resolve(m, "XAGUSD"); assert miss["broker"] is None and miss["status"] == "introuvable"
    assert resolve(m, "XAUUSD", {"XAUUSD": "MYGOLD"})["broker"] == "MYGOLD"


def test_alias_proxy_translates_reads_and_order_requests_without_mutating_the_original_request():
    m = GoldBroker(); a = AliasMT5(m, {"XAUUSD": "GOLD.a"})
    assert a.symbol_info("XAUUSD") is not None and m.seen[-1] == "GOLD.a" and a.symbol_select("XAUUSD", True)
    req = {"symbol": "XAUUSD", "volume": 0.01}; a.order_check(req); assert req["symbol"] == "XAUUSD" and m.checked[-1]["symbol"] == "GOLD.a"
    rec = []; m.order_send = lambda r: rec.append(r) or None; a.order_send(req)
    assert rec[-1]["symbol"] == "GOLD.a" and req["symbol"] == "XAUUSD"
    assert a.ACCOUNT_TRADE_MODE_DEMO == 0 and a.symbol_info("EURUSD.a") is not None                  # non-canonique : inchangé, attributs relayés


def test_maybe_alias_only_wraps_when_a_real_mapping_exists(tmp_path):
    m = GoldBroker(); assert maybe_alias(m, tmp_path) is m
    (tmp_path / "config").mkdir(); (tmp_path / "config" / "broker_profile.json").write_text(json.dumps({"symbol_map": {"XAUUSD": "GOLD.a"}}))
    assert isinstance(maybe_alias(m, tmp_path), AliasMT5)


def test_broker_profile_maps_symbols_samples_spread_and_never_assumes_zero_commission(tmp_path):
    m = GoldBroker(); prof = bp.build(m, ["XAUUSD", "XAGUSD"], 5, None, sleep=lambda s: None)
    assert prof["symbol_map"] == {"XAUUSD": "GOLD.a"} and "XAGUSD" in prof["unresolved"] and prof["account"]["login"] == "12**"
    c = prof["costs"]["XAUUSD"]; assert c["spread_frac"] == pytest.approx(0.08 / 2000.04, rel=1e-3) and c["fee_rate"] is None and "NON CONNUE" in c["fee_basis"]
    withc = bp.build(m, ["XAUUSD"], 3, 3.5, sleep=lambda s: None)["costs"]["XAUUSD"]; assert withc["fee_rate"] == pytest.approx(3.5 / (2000.04 * 100), rel=1e-3)
    assert bp.main(["--root", str(tmp_path), "--seconds", "2"], mt5=GoldBroker(), sleep=lambda s: None) == 0 and (tmp_path / "config" / "broker_profile.json").exists()
    assert m.sent == [] and m.checked == []


def test_non_demo_account_is_refused_by_the_profile():
    with pytest.raises(SystemExit, match="NON démo"):
        bp.build(GoldBroker(demo=False), ["XAUUSD"], 1, None, sleep=lambda s: None)
