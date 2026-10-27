import json
import pytest
from datetime import datetime, timezone

import pandas as pd
from fastapi.testclient import TestClient

from quantbot.data.autosync import AutoSync, sync_coinbase
from quantbot.data.coinbase import load_utc_csv, to_frame
from quantbot.gui.app import create_app

NOW = datetime(2026, 10, 25, 12, 7, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self): self.calls = []
    def fetch_range(self, product, tf, start, end):
        self.calls.append(start)
        t0 = int(start.timestamp()) // 900 * 900; rows = []
        while t0 < end.timestamp():
            rows.append([t0, 99.0, 101.0, 100.0, 100.5, 10.0]); t0 += 900
        return to_frame(rows[::-1], 900)


class Boom:
    def fetch_range(self, *a): raise OSError("réseau coupé")


def test_incremental_sync_appends_only_closed_new_bars_and_never_rewrites(tmp_path):
    c = FakeClient(); sync_coinbase(tmp_path, ["BTC-USD"], ["M15"], 1, c, NOW)
    first = load_utc_csv(tmp_path / "data" / "crypto" / "BTC-USD_M15.csv")
    assert first.index[-1] == pd.Timestamp("2026-10-25 11:45")            # la barre 12:00 n'est pas close à 12:07
    snap = first.copy()
    later = datetime(2026, 10, 25, 13, 1, tzinfo=timezone.utc); sync_coinbase(tmp_path, ["BTC-USD"], ["M15"], 1, c, later)
    second = load_utc_csv(tmp_path / "data" / "crypto" / "BTC-USD_M15.csv")
    assert c.calls[1] == datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc) and second.index[-1] == pd.Timestamp("2026-10-25 12:45")
    pd.testing.assert_frame_equal(second.loc[snap.index], snap) and second.index.is_unique


def test_network_failure_is_reported_not_faked(tmp_path):
    out = sync_coinbase(tmp_path, ["BTC-USD"], ["M15"], 1, Boom(), NOW)
    assert out[0]["status"] == "erreur" and "réseau coupé" in out[0]["error"] and not (tmp_path / "data" / "crypto" / "BTC-USD_M15.csv").exists()


def test_autosync_status_and_api(tmp_path):
    a = AutoSync(tmp_path, client=FakeClient(), mt5_enabled=False); st = a.run_once()
    assert st["orders_sent"] == 0 and json.loads((tmp_path / "data" / "sync_status.json").read_text())["cycle"] == 1
    r = TestClient(create_app(tmp_path), base_url="http://127.0.0.1").get("/api/sync").json()
    assert r["available"] and r["results"][0]["source"] == "coinbase"
    assert TestClient(create_app(tmp_path / "x"), base_url="http://127.0.0.1").get("/api/sync").json()["available"] is False


def test_mt5_absent_is_reported(tmp_path, monkeypatch):
    import sys; monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    from quantbot.data.autosync import sync_mt5, DEFAULTS
    assert sync_mt5(tmp_path, DEFAULTS["mt5"])["status"] == "indisponible"


class _Lvl:
    def __init__(self, t, price, volume): self.type, self.price, self.volume = t, price, volume


class FakeBookMT5:
    BOOK_TYPE_SELL, BOOK_TYPE_BUY = 1, 2
    def __init__(self, ok=True): self.ok = ok
    def market_book_add(self, s): return self.ok
    def market_book_get(self, s): return [_Lvl(2, 2399.9 - i * .1, 10 + i) for i in range(7)] + [_Lvl(1, 2400.1 + i * .1, 5 + i) for i in range(7)] if self.ok else None


def test_depth_sampler_records_real_book_levels_or_reports_unavailable(tmp_path):
    from quantbot.data.autosync import sample_depth
    assert sample_depth(FakeBookMT5(), tmp_path, "XAUUSD", 5, now=1_700_000_000.0)["status"] == "ok"
    f = next((tmp_path / "data" / "live" / "depth").glob("XAUUSD_*.jsonl")); rec = json.loads(f.read_text().splitlines()[0])
    assert len(rec["bids"]) == 5 and len(rec["asks"]) == 5 and rec["bids"][0][0] > rec["bids"][1][0] and rec["asks"][0][0] < rec["asks"][1][0]
    t2 = tmp_path / "x"; assert sample_depth(FakeBookMT5(ok=False), t2, "XAUUSD")["status"] == "carnet_indisponible" and not (t2 / "data").exists()


class FakeTickMT5:
    COPY_TICKS_ALL = -1
    def __init__(self): self.rows = [(1_700_000_000_000 + i * 500, 2400.0 + i * .01, 2400.1 + i * .01, 0.0, 0, 0) for i in range(6)]
    def last_error(self): return (1, "ok")
    def copy_ticks_from(self, symbol, start, n, flags):
        import numpy as np
        t0 = int(start.timestamp() * 1000); r = [x for x in self.rows if x[0] >= t0] or []
        return np.array(r, dtype=[("time_msc", "i8"), ("bid", "f8"), ("ask", "f8"), ("last", "f8"), ("volume", "u8"), ("flags", "u4")]) if r else None


def test_tick_recorder_appends_without_duplicates_and_reports_absence(tmp_path):
    from quantbot.data.autosync import sample_ticks
    m = FakeTickMT5(); m.rows = [(int(__import__("time").time() * 1000) - 5000 + i * 500, 2400.0 + i * .01, 2400.1 + i * .01, 0.0, 0, 0) for i in range(6)]
    r1 = sample_ticks(m, tmp_path, "XAUUSD"); r2 = sample_ticks(m, tmp_path, "XAUUSD")
    assert r1["status"] == "ok" and r1["appended"] == 6 and r2["appended"] == 0
    files = list((tmp_path / "data" / "live" / "ticks").glob("XAUUSD_*.csv")); assert sum(len(f.read_text().splitlines()) - 1 for f in files) == 6
    m2 = FakeTickMT5(); m2.rows = []; assert sample_ticks(m2, tmp_path / "y", "XAUUSD")["status"] == "aucun_tick"


def test_clock_offset_math_health_and_failure_reporting():
    from quantbot.clock import clock_health, clock_offset
    ok = clock_offset(query=lambda s, t: (100.0, 100.55, 100.56, 100.2))          # serveur en avance de ~0,455 s sur la machine : machine en retard
    assert ok["status"] == "ok" and ok["offset_s"] == pytest.approx(-0.455, abs=1e-3) and ok["round_trip_s"] == pytest.approx(0.19, abs=1e-3) and clock_health(ok) == "a_corriger"
    assert clock_health({"status": "ok", "offset_s": 0.01}) == "ok" and clock_health({"status": "ok", "offset_s": 5}) == "mauvaise"
    def boom(s, t): raise TimeoutError()
    bad = clock_offset(query=boom); assert bad["status"] == "injoignable" and clock_health(bad) == "inconnue"


def test_mt5_sync_refuses_to_write_when_another_daemon_holds_the_lock(tmp_path):
    from quantbot.data.autosync import DEFAULTS, sync_mt5
    from quantbot.filelock import exclusive_lock
    class Term: connected = True
    class Acct: trade_mode = 0
    class M:
        ACCOUNT_TRADE_MODE_DEMO = 0
        def initialize(self, *a, **k): return True
        def account_info(self): return Acct()
        def terminal_info(self): return Term()
        def shutdown(self): pass
    with exclusive_lock(tmp_path / "data" / "live" / "daemon.lock"):
        assert sync_mt5(tmp_path, DEFAULTS["mt5"], M())["status"] == "verrou_occupe"


def test_short_history_is_backfilled_towards_the_past_without_rewriting_stored_bars(tmp_path):
    c = FakeClient(); sync_coinbase(tmp_path, ["BTC-USD"], ["M15"], 3, c, NOW)
    f = tmp_path / "data" / "crypto" / "BTC-USD_M15.csv"; first = load_utc_csv(f); n0 = len(first)
    r = sync_coinbase(tmp_path, ["BTC-USD"], ["M15"], 30, c, NOW)
    second = load_utc_csv(f)
    assert r[0]["backfilled"] > 0 and len(second) > n0 * 5 and second.index.is_unique and second.index.is_monotonic_increasing
    pd.testing.assert_frame_equal(second.loc[first.index], first)
