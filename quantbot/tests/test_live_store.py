import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

from quantbot.data.live_store import LiveBarStore
from quantbot.data.mt5 import load_mt5_csv
from tests.fake_mt5_live import FakeMT5Live

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("data_daemon", ROOT / "scripts" / "data_daemon.py")
dd = importlib.util.module_from_spec(spec); spec.loader.exec_module(dd)


def test_bootstrap_then_incremental_never_stores_forming_bar_and_loads_with_the_normal_loader(tmp_path):
    m = FakeMT5Live(n_bars=300)
    st = LiveBarStore(tmp_path)
    r1 = st.update(m, "XAUUSD", "M15", n_bars=100)
    assert r1["bootstrap"] and r1["appended"] == 100
    assert st.last_epoch("XAUUSD", "M15") == m.bars[-2]["time"]                 # la barre en formation (-1) n'est pas stockée
    m.advance(5)
    r2 = st.update(m, "XAUUSD", "M15", n_bars=100)
    assert not r2["bootstrap"] and r2["appended"] == 5 and st.update(m, "XAUUSD", "M15", 100)["appended"] == 0   # idempotent
    df = load_mt5_csv(tmp_path / "XAUUSD_M15.csv")
    assert len(df) == 105 and df.index.is_monotonic_increasing
    assert st.verify()


def test_existing_bars_are_never_rewritten_and_a_change_is_reported(tmp_path):
    m = FakeMT5Live(n_bars=300)
    st = LiveBarStore(tmp_path); st.update(m, "XAUUSD", "M15", 100)
    before = (tmp_path / "XAUUSD_M15.csv").read_bytes()
    m.bars[-3]["close"] += 5.0                                                  # le terminal « révise » une barre clôturée
    r = st.update(m, "XAUUSD", "M15", 100)
    assert r.get("anomalies") == 1 and (tmp_path / "XAUUSD_M15.csv").read_bytes() == before
    assert json.loads((tmp_path / "ANOMALIES.jsonl").read_text().splitlines()[0])["kind"] == "barre_modifiee"


def test_gap_larger_than_window_triggers_backfill(tmp_path):
    m = FakeMT5Live(n_bars=600)
    st = LiveBarStore(tmp_path); st.update(m, "XAUUSD", "M15", 50)
    m.advance(300)                                                               # le démon était arrêté : 300 barres manquantes
    r = st.update(m, "XAUUSD", "M15", 50)
    assert r["appended"] == 300 and not r.get("gap_unfilled")
    assert len(load_mt5_csv(tmp_path / "XAUUSD_M15.csv")) == 50 + 300


def test_chain_detects_tampering(tmp_path):
    m = FakeMT5Live(n_bars=300)
    st = LiveBarStore(tmp_path); st.update(m, "XAUUSD", "M15", 100); m.advance(3); st.update(m, "XAUUSD", "M15", 100)
    assert st.verify()
    lines = (tmp_path / "MANIFEST.jsonl").read_text().splitlines()
    e = json.loads(lines[0]); e["n"] = 999; lines[0] = json.dumps(e)
    (tmp_path / "MANIFEST.jsonl").write_text("\n".join(lines) + "\n")
    assert not st.verify()


def test_daemon_survives_disconnects_writes_status_and_refuses_real_account(tmp_path, monkeypatch):
    m = FakeMT5Live(n_bars=300)
    m.initialize = lambda *a, **k: True
    m.terminal_info = lambda: NS(connected=False)
    assert dd.main(["--out", str(tmp_path), "--interval", "1"], mt5=m, sleep=lambda _: None, max_cycles=2) == 0
    s = json.loads((tmp_path / "DAEMON_STATUS.json").read_text())
    assert s["connected"] is False and s["orders_sent"] == 0 and not (tmp_path / "XAUUSD_M15.csv").exists()
    m.terminal_info = lambda: NS(connected=True)
    m.acct.trade_mode = m.ACCOUNT_TRADE_MODE_REAL
    dd.main(["--out", str(tmp_path), "--interval", "1"], mt5=m, sleep=lambda _: None, max_cycles=1)
    assert "non démo" in json.loads((tmp_path / "DAEMON_STATUS.json").read_text())["refused"]
    assert not (tmp_path / "XAUUSD_M15.csv").exists()


def test_daemon_collects_when_connected_and_second_instance_is_refused(tmp_path):
    m = FakeMT5Live(n_bars=300)
    m.initialize = lambda *a, **k: True; m.terminal_info = lambda: NS(connected=True)
    dd.main(["--out", str(tmp_path), "--interval", "1"], mt5=m, sleep=lambda _: m.advance(2), max_cycles=3)
    s = json.loads((tmp_path / "DAEMON_STATUS.json").read_text())
    assert s["connected"] and s["chain_ok"] and any(x.get("appended") for x in s["series"])
    from quantbot.filelock import exclusive_lock
    with exclusive_lock(tmp_path / "daemon.lock"):
        with pytest.raises(RuntimeError, match="déjà utilisé"):
            dd.main(["--out", str(tmp_path)], mt5=m, sleep=lambda _: None, max_cycles=1)


def test_no_order_api_anywhere_in_the_collection_path():
    forbidden = {"order_send", "order_check", "order_calc_margin", "order_calc_profit", "positions_get", "orders_get"}
    for f in (ROOT / "scripts" / "data_daemon.py", ROOT / "quantbot" / "data" / "live_store.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert not called & forbidden, f
