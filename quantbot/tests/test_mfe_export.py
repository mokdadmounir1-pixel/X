import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quantbot.gui.app import create_app
from quantbot.live.state import StateStore
from quantbot.ui import mfe_export as me
from tests.test_quant3 import _write_live

ROOT = Path(__file__).resolve().parents[1]


def _bars():
    idx = pd.date_range("2024-01-02 09:00", periods=40, freq="15min"); c = np.full(40, 100.0); h = c + 0.2; l = c - 0.2
    h[5] = 103.0; l[9] = 97.0; h[12] = 105.0                                     # extrêmes connus
    return pd.DataFrame({"open": c, "high": h, "low": l, "close": c, "volume": 100.0}, index=idx)


def _trade(side, entry, stop, tp, t0, t1, r, reason, pnl):
    return json.dumps({"side": side, "reason": reason, "pnl": pnl, "r": r, "t": str(t1), "entry": entry, "exit": entry, "entry_time": str(t0), "exit_time": str(t1), "stop": stop, "tp": tp, "paper": True, "size": 1.0,
                       "strategy": "vwap", "symbol": "XAUUSD", "recorded_ms": 1700000000000})


def _root(tmp_path):
    df = _bars(); _write_live(tmp_path, "XAUUSD", df)
    db = tmp_path / "runtime" / "paper"; db.mkdir(parents=True); s = StateStore(db / "XAUUSD_vwap.db"); s.set("strategy", "vwap"); s.set("symbol", "XAUUSD")
    t = df.index
    s.log("INFO", "trade", _trade("long", 100.0, 98.0, 104.0, t[2], t[10], -1.0, "stop_loss", -100.0))          # perdant : a monté à 103 (+1,5 R) avant d'être stoppé
    s.log("INFO", "trade", _trade("short", 100.0, 102.0, 96.0, t[2], t[10], -1.0, "stop_loss", -100.0))         # perdant vendeur : bas à 97 (+1,5 R)
    s.log("INFO", "trade", _trade("long", 100.0, 98.0, 104.0, t[11], t[13], 2.0, "take_profit", 200.0))         # TP : plus haut 105 (+2,5 R)
    return tmp_path


def test_mfe_values_losers_with_positive_mfe_tp_and_totals(tmp_path):
    res = me.build_export(_root(tmp_path)); rows = {r["id"]: r for r in res["rows"]}; assert len(rows) == 3
    by = {(r["side"], r["is_tp"]): r for r in rows.values()}
    long_loser, short_loser, tp = by[("long", False)], by[("short", False)], by[("long", True)]
    assert long_loser["mfe_r"] == pytest.approx(1.5, abs=1e-6) and long_loser["loser_with_positive_mfe"] is True and long_loser["giveback_r"] == pytest.approx(2.5)
    assert short_loser["mfe_r"] == pytest.approx(1.5, abs=1e-6) and tp["mfe_r"] == pytest.approx(2.5, abs=1e-6) and tp["is_tp"] is True and tp["mae_r"] >= 0
    s = res["summary"]; assert s["trades_closed"] == 3 and s["all_closed"]["sum_mfe_r"] == pytest.approx(5.5) and s["losers"]["n"] == 2 and s["losers_with_positive_mfe"]["n"] == 2
    assert s["losers"]["sum_mfe_r"] == pytest.approx(3.0) and s["take_profit"]["n"] == 1 and s["take_profit"]["sum_mfe_r"] == pytest.approx(2.5) and s["losers_with_positive_mfe"]["n_mfe_ge_1r"] == 2
    assert s["by_strategy"]["VWAP_BAND_M15"]["n_tp"] == 1


def test_trades_without_bars_are_flagged_not_invented_and_mfe_is_never_negative(tmp_path):
    root = _root(tmp_path)
    for f in (root / "data" / "live").glob("*.csv"): f.rename(f.with_suffix(".bak"))
    res = me.build_export(root); assert all(r["note"] == "sans_barres" and r["mfe_r"] is None for r in res["rows"]) and res["summary"]["closed_without_bars"] == 3
    df = _bars(); e = me.excursions(df, "long", 200.0, 198.0, df.index[0], df.index[5]); assert e["mfe_price"] == 0.0 and e["mae_r"] > 0


def test_csv_endpoint_and_script_write_the_same_rows(tmp_path):
    root = _root(tmp_path); c = TestClient(create_app(root), base_url="http://127.0.0.1")
    r = c.get("/api/trades_mfe.csv"); assert r.status_code == 200 and r.text.startswith("﻿") and r.text.count("\n") == 4 and "mfe_r" in r.text.split("\n")[0]
    assert c.get("/api/trades_mfe").json()["summary"]["trades_closed"] == 3
    sp = importlib.util.spec_from_file_location("emfe", ROOT / "scripts" / "export_trades_mfe.py"); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
    assert m.main(["--root", str(root)]) == 0 and (root / "reports" / "exports" / "trades_mfe.csv").read_text(encoding="utf-8").count("\n") == 4
    assert "Perdants qui avaient un plus haut POSITIF" in (root / "reports" / "exports" / "trades_mfe_summary.md").read_text(encoding="utf-8")
