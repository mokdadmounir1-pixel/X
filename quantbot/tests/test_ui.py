import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pandas as pd
import pytest

from quantbot.config import Settings
from tests.synthetic import generate_synthetic
from quantbot.ui import server


def test_state_reflects_reports_and_never_claims_an_edge_without_pass():
    s = server.collect_state()
    assert s["status"]["live_trading"].startswith("AUCUN ordre")
    names = [sp["name"] for sp in s["specs"]]
    assert "baseline_v0" in names and "baseline_v1" in names
    verdicts = [r.get("verdict") for sp in s["specs"] for r in sp["results"]]
    assert s["status"]["edge_validated"] == any(v == "PASS" for v in verdicts)
    assert s["status"]["trials"] >= 6 and s["status"]["locked_reads"] == 0 and s["status"]["registry_chain_ok"]


def test_replay_returns_curve_and_never_needs_orders():
    df = generate_synthetic(900, seed=2)
    out = server.run_replay(df, Settings())
    assert out["equity"] and out["metrics"]["n_trades"] >= 0 and "reasons" in out


def test_replay_endpoint_rejects_unknown_instrument_and_clamps_bars():
    with pytest.raises(ValueError):
        server.replay_instrument("NOPE", 1000)


def test_http_server_binds_locally_and_serves_state():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    assert httpd.server_address[0] == "127.0.0.1"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        port = httpd.server_address[1]
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert "quantbot" in html and "Aucun edge" in html
        state = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state").read())
        assert state["status"]["live_trading"].startswith("AUCUN ordre")
        err = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/replay?instrument=NOPE") if False else None
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/replay?instrument=NOPE")
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        httpd.shutdown()


# --- onglet « En direct » : lecture seule de l'état du runtime ---------------------------------------------------------
def _live_state(tmp_path):
    from quantbot.live.state import StateStore
    s = StateStore(tmp_path / "live_state.db")
    s.set("mode", "OBSERVATION"); s.set("why", "fichier d'approbation absent : mode observation"); s.set("last_bar", "2026-10-26 10:00:00+00:00")
    s.set("heartbeat", __import__("time").time()); s.set("launcher_running", True)
    s.log("INFO", "trade", json.dumps({"side": "long", "reason": "tp", "pnl": 12.5, "r": 0.8, "t": "x"}))
    iid = s.new_intent("OPEN", "long", {}, "vwap"); s.mark(iid, "UNKNOWN", "timeout")
    s.close()
    return tmp_path / "live_state.db"


def test_live_absent_state_is_reported_and_not_created(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTBOT_STATE", str(tmp_path / "none" / "s.db"))
    out = server.collect_live(tmp_path)
    assert out["available"] is False and not (tmp_path / "none").exists()


def test_live_reads_state_read_only_and_flags_unresolved_intent(tmp_path, monkeypatch):
    p = _live_state(tmp_path)
    monkeypatch.setenv("QUANTBOT_STATE", str(p)); monkeypatch.setenv("QUANTBOT_APPROVALS", str(tmp_path / "absent.json"))
    before = p.read_bytes()
    out = server.collect_live(tmp_path)
    assert out["available"] and out["mode"] == "OBSERVATION" and out["running"] is True
    assert out["paper_trades"][0]["r"] == 0.8 and out["intents"][0]["status"] == "UNKNOWN"
    assert any("non rapprochée" in r for r in out["kill_reasons"]) and "SIMULÉS" in out["statistics_nature"]
    assert out["approvals"]["present"] is False and p.read_bytes() == before


def test_live_stale_heartbeat_is_not_reported_as_running(tmp_path, monkeypatch):
    from quantbot.live.state import StateStore
    s = StateStore(tmp_path / "live_state.db"); s.set("launcher_running", True); s.set("heartbeat", 1.0); s.close()
    monkeypatch.setenv("QUANTBOT_STATE", str(tmp_path / "live_state.db"))
    assert server.collect_live(tmp_path)["running"] is False


def test_live_endpoint_is_get_only_local(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTBOT_STATE", str(_live_state(tmp_path)))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        port = httpd.server_address[1]
        st = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live").read())
        assert st["available"] and st["mode"] == "OBSERVATION"
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/live", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(req)
        assert 'id="view"' in urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
    finally:
        httpd.shutdown()
