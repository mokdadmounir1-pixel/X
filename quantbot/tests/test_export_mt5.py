import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location("export_mt5", Path(__file__).resolve().parents[1] / "scripts" / "export_mt5.py")
exp = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(exp)


class FakeMT5:
    TIMEFRAME_M1, TIMEFRAME_H1 = 1, 16385

    def __init__(self, n=500, dup=True):
        t0 = 1_700_000_000
        rows = [{"time": t0 + 60 * i, "open": 2000 + i * .1, "high": 2000.5 + i * .1, "low": 1999.5 + i * .1, "close": 2000.2 + i * .1,
                 "tick_volume": 100 + i, "spread": 12, "real_volume": 0} for i in range(n)]
        if dup:
            rows.insert(10, dict(rows[10]))      # doublon à nettoyer
        self.rows, self.calls = rows, []

    def initialize(self): return True
    def shutdown(self): pass
    def last_error(self): return (0, "ok")
    def symbol_info(self, s): return SimpleNamespace(point=0.01, digits=2)
    def symbol_select(self, s, e): return True
    def account_info(self): return SimpleNamespace(server="Fake-Demo")

    def copy_rates_from_pos(self, symbol, tf, start, n):
        self.calls.append((symbol, tf, start, n))
        return self.rows[-n:] if n < len(self.rows) else self.rows


def test_export_format_dedup_sort_and_provenance(tmp_path):
    fake = FakeMT5()
    assert exp.main(["--symbol", "XAUUSD", "--timeframes", "M1", "H1", "--out", str(tmp_path)], mt5=fake) == 0
    assert all(c[2] == 1 for c in fake.calls)  # position 1 : la barre en formation (position 0) n'est jamais lue
    df = pd.read_csv(tmp_path / "XAUUSD_M1.csv")
    assert list(df.columns) == exp.COLUMNS and df["time_broker_epoch"].is_monotonic_increasing and not df["time_broker_epoch"].duplicated().any()
    assert np.allclose(df["spread"], 0.12) and (df["spread_points"] == 12).all()
    prov = json.loads((tmp_path / "EXPORT-PROVENANCE.json").read_text(encoding="utf-8"))
    assert prov["orders_sent"] == 0 and prov["synthetic"] is False and len(prov["instruments"]) == 2
    import hashlib
    assert prov["instruments"][0]["sha256"] == hashlib.sha256((tmp_path / "XAUUSD_M1.csv").read_bytes()).hexdigest()
    assert prov["instruments"][0]["invalid_ohlc"] == 0 and prov["instruments"][0]["median_step_min"] == 1


def test_exported_file_loads_with_quantbot_loader(tmp_path):
    from quantbot.data.mt5 import load_mt5_csv
    exp.main(["--symbol", "XAUUSD", "--timeframes", "M1", "--out", str(tmp_path)], mt5=FakeMT5(dup=False))
    out = load_mt5_csv(tmp_path / "XAUUSD_M1.csv")
    assert len(out) == 500 and (out["spread"] > 0).all() and out.index.is_monotonic_increasing


def test_unknown_timeframe_and_missing_symbol_fail_loudly(tmp_path):
    with pytest.raises(SystemExit):
        exp.main(["--timeframes", "M7", "--out", str(tmp_path)], mt5=FakeMT5())
    bad = FakeMT5(); bad.symbol_info = lambda s: None
    with pytest.raises(SystemExit):
        exp.main(["--out", str(tmp_path)], mt5=bad)


def test_export_script_contains_no_order_call():
    src = (Path(exp.__file__)).read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith(("#", '"""')) )
    assert "order_send" not in code.replace("AUCUN appel d'ordre", "") and "order_check" not in code
