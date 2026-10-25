import json

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


def test_terminal_serves_local_only_read_only_and_ships_its_assets():
    from fastapi.testclient import TestClient
    from quantbot.gui.app import create_app
    c = TestClient(create_app(), base_url="http://127.0.0.1")
    html = c.get("/").text
    assert "quantbot" in html and "/js/app.js" in html and "lightweight-charts" in html
    for asset in ("/css/terminal.css", "/js/app.js", "/js/grid.js", "/js/chart.js", "/vendor/lightweight-charts.standalone.production.js", "/vendor/LICENSE-lightweight-charts.txt", "/assets/fennec_diamond.png"):
        assert c.get(asset).status_code == 200, asset
    st = c.get("/api/state").json()
    assert st["status"]["live_trading"].startswith("AUCUN ordre") and "objective" in st
    assert c.get("/api/health").json() == {"ok": True, "read_only": True}
    assert c.get("/api/health", headers={"host": "evil.example.com"}).status_code == 403            # protection DNS rebinding
    for verb in (c.post, c.put, c.delete, c.patch):
        assert verb("/api/state").status_code in (404, 405)                                        # aucune écriture possible
    assert c.get("/api/strategy_replay?instrument=NOPE&strategy=orb").status_code == 400
    assert c.get("/api/book?period=forever").status_code == 422


def test_gui_server_binds_to_loopback_only():
    from quantbot.gui import server
    assert server.HOST == "127.0.0.1" and server.DEFAULT_PORT == 8877 and server.free_port() >= 8877


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


def test_live_endpoint_serves_state(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from quantbot.gui.app import create_app
    monkeypatch.setenv("QUANTBOT_STATE", str(_live_state(tmp_path)))
    out = TestClient(create_app(), base_url="http://127.0.0.1").get("/api/live").json()
    assert out["available"] and out["mode"] == "OBSERVATION"


# --- test de stratégie trade par trade (entrées / SL / TP / sorties) ----------------------------------------------------
import pytest as _pytest
from pathlib import Path as _Path

_REAL = _Path(__file__).resolve().parents[1] / "data" / "real" / "USTEC_M15.csv"


def test_daily_stats_counts_days_without_trade_as_zero():
    from types import SimpleNamespace as NS
    from quantbot.ui.replay import daily_stats
    idx = pd.date_range("2024-01-01", periods=5 * 96, freq="15min")          # 5 jours ouvrés (lun-ven)
    df = pd.DataFrame({"close": 1.0}, index=idx)
    trades = [NS(exit_time=idx[10], r_nominal=1.0), NS(exit_time=idx[200], r_nominal=-0.5)]
    d = daily_stats(trades, df, 0.33)
    assert d["window_days"] == 5 and d["total_R"] == 0.5 and abs(d["avg_R_per_day"] - 0.1) < 1e-9
    assert d["days_with_trade"] == 2 and abs(d["days_ge_target_pct"] - 0.2) < 1e-9


@_pytest.mark.skipif(not _REAL.exists(), reason="exports MT5 absents (data/real non suivi par Git)")
def test_strategy_replay_returns_every_trade_with_levels_and_never_the_locked_period():
    from quantbot.ui.replay import run_strategy_replay
    out = run_strategy_replay("USTEC", 3000, "orb", "recherche", _Path(__file__).resolve().parents[1])
    assert out["trades"] and out["metrics"]["n_trades"] == len(out["trades"]) and out["daily"]["target"] == 0.33
    for t in out["trades"]:
        assert t["stop"] and t["tp"] and 0 <= t["i0"] <= t["i1"] < out["n_bars"]
        assert (t["stop"] < t["entry"] < t["tp"]) if t["side"] == "long" else (t["tp"] < t["entry"] < t["stop"])
    from quantbot.data.mt5 import load_mt5_csv
    from quantbot.lab.locked import split_locked
    full = load_mt5_csv(_REAL)
    research, locked = split_locked(full, 12, 0.2)
    assert pd.Timestamp(out["end"]) <= research.index[-1]                          # jamais la période verrouillée


def test_strategy_endpoints_reject_unknown_values():
    from quantbot.ui.replay import run_strategy_replay
    with pytest.raises(ValueError):
        run_strategy_replay("NOPE", 1000, "orb", "recherche", _Path(__file__).resolve().parents[1])
    with pytest.raises(ValueError):
        run_strategy_replay("USTEC", 1000, "orb", "verrouille", _Path(__file__).resolve().parents[1])


def test_port_is_dedicated_configurable_and_never_shared(monkeypatch):
    import socket
    from quantbot.gui import server
    monkeypatch.delenv("QUANTBOT_PORT", raising=False)
    assert server.configured_port() == 8877 and server.configured_port(9100) == 9100
    monkeypatch.setenv("QUANTBOT_PORT", "9123"); assert server.configured_port() == 9123
    monkeypatch.setenv("QUANTBOT_PORT", "abc"); assert server.configured_port() == 8877
    with socket.socket() as s:                                   # un autre programme occupe déjà le port voulu : on ne s'y superpose pas
        s.bind(("127.0.0.1", 0)); busy = s.getsockname()[1]; s.listen()
        assert server.free_port(busy) != busy
