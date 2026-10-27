import json
import time

from fastapi.testclient import TestClient

from quantbot.gui.app import create_app
from quantbot.risk.ledger import LedgerMonitor, enforce, evaluate, prometheus

NOW = 1_800_000_000.0


def _row(pnl, ms, code="S1", open_=False):
    return {"pnl": pnl, "recorded_ms": ms, "strategy_code": code, "open": open_}


def test_aggregates_all_strategies_as_one_account_and_limits_are_percent_of_capital():
    rows = [_row(-1500.0, NOW * 1000), _row(-1000.0, NOW * 1000, "S2"), _row(500.0, (NOW - 3 * 86400) * 1000), _row(-300.0, NOW * 1000, "S1", True)]
    st = evaluate(rows, NOW)
    assert st["pnl_today"] == -2800.0 and st["daily_pct"] == -0.028 and st["total_pct"] == -0.023 and not st["halt_new"] and not st["breached"]
    assert {a["strategy_code"]: a["pnl"] for a in st["by_strategy"]} == {"S1": -1300.0, "S2": -1000.0}


def test_buffer_halts_new_entries_hard_limit_marks_breach_and_kill_file_is_never_removed(tmp_path):
    st = evaluate([_row(-4200.0, NOW * 1000)], NOW); assert st["halt_new"] and not st["breached"] and "tampon" in st["reasons"][0]
    assert enforce(tmp_path, st) and (tmp_path / "runtime" / "paper" / "KILL").exists()
    ok = evaluate([_row(-100.0, NOW * 1000)], NOW); assert not ok["halt_new"] and enforce(tmp_path, ok) is True          # le KILL reste posé : levée humaine seulement
    hard = evaluate([_row(-5100.0, NOW * 1000)], NOW); assert hard["breached"] and "LIMITE DURE" in hard["reasons"][-1]
    assert evaluate([_row(-9000.0, (NOW - 2 * 86400) * 1000), _row(-1100.0, (NOW - 86400) * 1000)], NOW)["breached"]       # perte TOTALE de 10 %


def test_monitor_reads_the_real_book_and_endpoints_expose_ledger_and_prometheus_text(tmp_path):
    c = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    j = c.get("/api/ledger").json(); assert j["n_closed"] == 0 and j["halt_new"] is False and j["kill_file_present"] is False
    m = c.get("/metrics"); assert m.status_code == 200 and "quantbot_equity 100000.00" in m.text and "quantbot_halt_new 0" in m.text
    st = LedgerMonitor(tmp_path).tick(); assert (tmp_path / "runtime" / "ledger.json").exists() and st["kill_file"] is False
    text = prometheus(evaluate([_row(120.0, NOW * 1000, "A")], NOW)); assert 'quantbot_strategy_pnl{strategy="A"} 120.00' in text
