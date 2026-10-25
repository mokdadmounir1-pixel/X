import json
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
