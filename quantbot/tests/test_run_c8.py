import ast
import importlib.util
from pathlib import Path

import pandas as pd

S = Path(__file__).resolve().parents[1] / "scripts" / "run_c8.py"
sp = importlib.util.spec_from_file_location("run_c8", S); c8 = importlib.util.module_from_spec(sp); sp.loader.exec_module(c8)


def frame(epochs, close=1.0):
    return pd.DataFrame({"time_broker_epoch": epochs, "open": 1.0, "high": 2.0, "low": 0.5, "close": close})


def test_overlap_identical_and_earlier_bars_counted(tmp_path):
    frame(range(100, 200, 10)).to_csv(tmp_path / "real.csv", index=False)
    frame(range(0, 200, 10)).to_csv(tmp_path / "deep.csv", index=False)
    o = c8.overlap_diff(tmp_path / "deep.csv", tmp_path / "real.csv")
    assert o == {"common": 10, "reference_rows": 10, "reference_missing_in_deep": 0, "rows_different": 0, "cells_different": 0, "earlier_bars_added": 10, "deep_rows": 20}


def test_overlap_detects_a_changed_bar_and_a_missing_reference_bar(tmp_path):
    frame(range(100, 200, 10)).to_csv(tmp_path / "real.csv", index=False)
    d = frame(range(0, 190, 10)); d.loc[d.time_broker_epoch == 120, "close"] = 1.5
    d.to_csv(tmp_path / "deep.csv", index=False)
    o = c8.overlap_diff(tmp_path / "deep.csv", tmp_path / "real.csv")
    assert o["rows_different"] == 1 and o["reference_missing_in_deep"] == 1


def test_manifest_covers_every_file_except_itself(tmp_path):
    (tmp_path / "a.txt").write_text("x"); (tmp_path / "sub").mkdir(); (tmp_path / "sub" / "b.txt").write_text("y")
    (tmp_path / "manifest-sha256.json").write_text("[]")
    assert [e["file"] for e in c8.build_manifest(tmp_path)] == ["a.txt", "sub/b.txt"]


def test_orchestrator_never_calls_order_apis():
    called = {n.func.attr for n in ast.walk(ast.parse(S.read_text(encoding="utf-8"))) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not called & {"order_send", "order_check", "order_calc_margin", "order_calc_profit", "positions_get", "orders_get"}
