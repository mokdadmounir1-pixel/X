import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

from tests.fake_mt5_live import FakeMT5Live
from tests.test_live_runner import SPEC, approvals, runner

S = Path(__file__).resolve().parents[1] / "scripts" / "paper_all.py"
sp = importlib.util.spec_from_file_location("paper_all", S); pa = importlib.util.module_from_spec(sp); sp.loader.exec_module(pa)


def test_force_observation_ignores_a_valid_approval_and_never_builds_an_order_broker(tmp_path):
    m = FakeMT5Live(n_bars=1500)
    appr = approvals(tmp_path, strategy="fvg_h1")                       # approbation VALIDE présente
    from quantbot.live.runner import LiveRunner
    r = LiveRunner(m, "XAUUSD", "fvg_h1", SPEC, appr, tmp_path / "s.db", tmp_path / "KILL", force_observation=True)
    assert r.setup() == "OBSERVATION" and "PAPER" in r.state.get("why")
    from quantbot.execution.broker import PaperBroker
    assert isinstance(r.engine.broker, PaperBroker)
    r.engine.signals = __import__("tests.test_live_runner", fromlist=["OneShotSignal"]).OneShotSignal()
    for _ in range(14):
        m.advance(1); r.step()
    assert m.sent == [] and m.checked == []                              # aucun ordre, aucun order_check


def test_combos_come_from_the_preregistered_spec():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    c = pa.combos(spec)
    assert len(c) == 13 and ("USTEC", "orb") in c and ("EURUSD", "orb") not in c
    assert pa.combos(spec, symbols=["XAUUSD"], strategies=["vwap"]) == [("XAUUSD", "vwap")]


def test_main_runs_several_runners_paper_only_and_writes_one_db_each(tmp_path):
    m = FakeMT5Live(n_bars=1500); m.initialize = lambda *a, **k: True
    rc = pa.main(["--out", str(tmp_path), "--symbols", "XAUUSD", "--strategies", "vwap", "fvg_h1", "--poll", "1"], mt5=m, sleep=lambda _: m.advance(1), max_cycles=4)
    assert rc == 0 and m.sent == [] and m.checked == []
    assert (tmp_path / "XAUUSD_vwap.db").exists() and (tmp_path / "XAUUSD_fvg_h1.db").exists()
    st = json.loads((tmp_path / "STATUS.json").read_text())
    assert sorted(st["runners"]) == ["XAUUSD_fvg_h1", "XAUUSD_vwap"] and st["errors"] == []


def test_real_account_refuses_the_simulation(tmp_path, capsys):
    m = FakeMT5Live(n_bars=1500, demo=False); m.initialize = lambda *a, **k: True
    assert pa.main(["--out", str(tmp_path), "--symbols", "XAUUSD", "--strategies", "vwap"], mt5=m, sleep=lambda _: None, max_cycles=1) == 1
    assert "démo" in capsys.readouterr().out and not list(tmp_path.glob("*.db"))


def test_ui_aggregates_the_paper_runners_read_only(tmp_path, monkeypatch):
    from quantbot.ui import server
    m = FakeMT5Live(n_bars=1500); m.initialize = lambda *a, **k: True
    pa.main(["--out", str(tmp_path), "--symbols", "XAUUSD", "--strategies", "vwap", "fvg_h1", "--poll", "1"], mt5=m, sleep=lambda _: m.advance(1), max_cycles=4)
    before = {p.name: p.read_bytes() for p in tmp_path.glob("*.db")}
    monkeypatch.setenv("QUANTBOT_PAPER", str(tmp_path))
    out = server.collect_paper(Path(__file__).resolve().parents[1])
    assert out["available"] and {r["id"] for r in out["runners"]} == {"XAUUSD_vwap", "XAUUSD_fvg_h1"} and all(r["mode"] == "OBSERVATION" for r in out["runners"])
    assert out["selected"]["id"] in {"XAUUSD_vwap", "XAUUSD_fvg_h1"} and len(out["selected"]["bars"]) > 10
    assert server.collect_paper(Path(__file__).resolve().parents[1], "../etc")["selected"] is None          # pas d'évasion de chemin
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.db")} == before                                 # lecture seule


def test_ui_paper_absent_dir_is_reported_not_created(tmp_path, monkeypatch):
    from quantbot.ui import server
    monkeypatch.setenv("QUANTBOT_PAPER", str(tmp_path / "none"))
    out = server.collect_paper(Path(__file__).resolve().parents[1])
    assert out["available"] is False and not (tmp_path / "none").exists()


def test_coinbase_source_paper_runs_without_mt5_and_never_builds_an_order_broker(tmp_path):
    from quantbot.data.coinbase import CoinbaseClient
    from tests.test_coinbase import T0, fake_market
    rows, get, _ = fake_market(4000)
    now = {"t": T0 + 3500 * 900 + 300}
    import quantbot.data.coinbase as cb
    orig = cb.CoinbaseFeed.__init__
    def init(self, product, timeframe="M15", n_bars=3000, client=None, clock=None, **k):   # horloge de test injectée
        orig(self, product, timeframe, n_bars, client, lambda: now["t"], **k)
    cb.CoinbaseFeed.__init__ = init
    try:
        def sleep(_):
            now["t"] += 900
        rc = pa.main(["--source", "coinbase", "--out", str(tmp_path), "--symbols", "BTC-USD", "--strategies", "vwap", "fvg_h1", "--poll", "1"],
                     mt5=None, sleep=sleep, max_cycles=4, coinbase_client=CoinbaseClient(get=get, sleep=lambda _: None))
    finally:
        cb.CoinbaseFeed.__init__ = orig
    assert rc == 0 and (tmp_path / "BTC-USD_vwap.db").exists() and (tmp_path / "BTC-USD_fvg_h1.db").exists()
    st = json.loads((tmp_path / "STATUS_coinbase.json").read_text())
    assert st["source"] == "coinbase" and st["errors"] == [] and sorted(st["runners"]) == ["BTC-USD_fvg_h1", "BTC-USD_vwap"]
    from quantbot.ui import server
    import os
    os.environ["QUANTBOT_PAPER"] = str(tmp_path)
    try:
        out = server.collect_paper(Path(__file__).resolve().parents[1])
    finally:
        del os.environ["QUANTBOT_PAPER"]
    assert all(r["mode"] == "OBSERVATION" and r["source"] == "Coinbase" for r in out["runners"])
