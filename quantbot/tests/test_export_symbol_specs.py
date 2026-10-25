import ast
import importlib.util
import json
from pathlib import Path

from tests.fake_mt5_live import FakeMT5Live

S = Path(__file__).resolve().parents[1] / "scripts" / "export_symbol_specs.py"
sp = importlib.util.spec_from_file_location("ess", S); ess = importlib.util.module_from_spec(sp); sp.loader.exec_module(ess)


def test_export_is_read_only_and_marks_missing_fields_as_null(tmp_path):
    m = FakeMT5Live(); m.initialize = lambda *a, **k: True
    out = tmp_path / "s.json"
    assert ess.main(["--symbols", "XAUUSD", "--out", str(out)], mt5=m) == 0
    d = json.loads(out.read_text())
    assert d["orders_sent"] == 0 and d["symbols"]["XAUUSD"]["trade_contract_size"] == 100 and d["symbols"]["XAUUSD"]["swap_long"] is None   # jamais inventé
    called = {n.func.attr for n in ast.walk(ast.parse(S.read_text())) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not called & {"order_send", "order_check", "order_calc_margin", "order_calc_profit", "positions_get", "orders_get"}
