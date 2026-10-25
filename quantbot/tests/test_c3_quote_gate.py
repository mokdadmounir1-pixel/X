import ast
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "c3_quote_gate.py"


def test_gate_uses_only_read_apis():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not called & {"order_send", "order_check", "order_calc_margin", "positions_get", "orders_get"}
    assert {"initialize", "symbol_info_tick", "account_info", "shutdown"} <= called
