import ast
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quantbot.data.mt5 import load_mt5_csv
from tests.fake_mt5_live import FakeMT5Live

S = Path(__file__).resolve().parents[1] / "scripts" / "export_mt5_deep.py"
sp = importlib.util.spec_from_file_location("emd", S); emd = importlib.util.module_from_spec(sp); sp.loader.exec_module(emd)


def _fake():
    m = FakeMT5Live(n_bars=2000); m.initialize = lambda *a, **k: True
    return m


def test_chunked_export_recovers_every_closed_bar_without_duplicates(tmp_path, monkeypatch):
    m = _fake()
    last = datetime.fromtimestamp(m.bars[-1]["time"] + 3600, timezone.utc)
    monkeypatch.setitem(emd.CHUNK_DAYS, "M15", 3)
    raw, notes = emd.deep_rates(m, "XAUUSD", "M15", 3, now=last, sleep=lambda _: None)
    assert len(raw) == len(m.bars) - 1 and raw["time"].is_unique and raw["time"].is_monotonic_increasing   # dernière barre écartée
    assert raw["time"].iloc[0] == m.bars[0]["time"]


def test_main_writes_loadable_csv_provenance_and_survives_a_failing_timeframe(tmp_path, monkeypatch):
    m = _fake()
    monkeypatch.setattr(emd, "CHUNK_DAYS", {"M15": 3, "H1": 3})
    fixed = datetime.fromtimestamp(m.bars[-1]["time"] + 3600, timezone.utc)
    real = emd.deep_rates
    monkeypatch.setattr(emd, "deep_rates", lambda mt5, s, tf, cd, max_empty=3: real(mt5, s, tf, cd, max_empty, now=fixed, sleep=lambda _: None)
                        if tf == "M15" else (_ for _ in ()).throw(RuntimeError("Terminal: Call failed")))
    rc = emd.main(["--symbol", "XAUUSD", "--timeframes", "M15", "H1", "--out", str(tmp_path)], mt5=m)
    assert rc == 0
    meta = json.loads((tmp_path / "EXPORT-PROVENANCE-DEEP-XAUUSD.json").read_text())
    assert meta["orders_sent"] == 0 and len(meta["instruments"]) == 1 and meta["failures"][0]["timeframe"] == "H1"   # l'échec n'est pas masqué
    assert len(load_mt5_csv(tmp_path / "XAUUSD_M15.csv")) > 1000


def test_deep_export_never_calls_order_apis():
    called = {n.func.attr for n in ast.walk(ast.parse(S.read_text(encoding="utf-8"))) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not called & {"order_send", "order_check", "order_calc_margin", "order_calc_profit", "positions_get", "orders_get"}
