import importlib.util
import numpy as np
import pytest

from quantbot.audit import execution_stats, gatekeeper, tick_inventory, trade_metrics


def test_metrics_match_hand_computation():
    m = trade_metrics([2.0, -1.0, 2.0, -1.0, -1.0, 2.0])             # 3 gains de 2, 3 pertes de 1
    assert m["n"] == 6 and m["win_rate"] == 0.5 and m["realised_rr"] == 2.0 and m["breakeven_wr"] == pytest.approx(1 / 3)
    assert m["expectancy_r"] == pytest.approx(0.5) and m["profit_factor"] == pytest.approx(2.0) and m["max_drawdown_r"] == 2.0
    assert trade_metrics([]) == {"n": 0}


def test_gatekeeper_marks_unmeasured_and_fails_small_samples_and_trap_win_rates():
    trap = trade_metrics([0.3] * 65 + [-1.0] * 35)                       # 65 % de réussite, R:R 0,3 : piège
    g = {c["check"]: c["state"] for c in gatekeeper(trap)}
    assert g["échantillon >= 60 trades"] == "OK" and g["espérance nette > 0"] == "ECHEC" and g["taux de réussite > seuil d'équilibre"] == "ECHEC"
    assert g["latence max <= 25 ms"] == "NON MESURE" and g["drawdown <= 0.80%"] == "NON MESURE"
    assert {c["check"]: c["state"] for c in gatekeeper(trade_metrics([1.0] * 10))}["échantillon >= 60 trades"] == "ECHEC"
    assert {c["check"]: c["state"] for c in gatekeeper(trade_metrics([1.0, -0.5] * 40), latency_ms={"max": 40.0})}["latence max <= 25 ms"] == "ECHEC"


def test_execution_stats_and_tick_inventory(tmp_path):
    ex = execution_stats([{"latency_ms": 10.0, "slippage": 0.1}, {"latency_ms": 30.0, "slippage": -0.05}]); assert ex["latency_ms"]["max"] == 30.0 and ex["slippage"]["mean"] == pytest.approx(0.025)
    assert execution_stats([]) == {} and tick_inventory(tmp_path)["files"] == 0
    d = tmp_path / "data" / "live" / "ticks"; d.mkdir(parents=True)
    import pandas as pd
    pd.DataFrame({"time_msc": [1_700_000_000_000 + i * 500 for i in range(100)], "bid": 2400.0, "ask": [2400.02 if i % 2 else 2400.10 for i in range(100)]}).to_csv(d / "XAUUSD_20231114.csv", index=False)
    inv = tick_inventory(tmp_path); assert inv["ticks"] == 100 and inv["share_spread_le_0_03"] == pytest.approx(0.5) and inv["max_gap_s"] == pytest.approx(0.5)


def test_audit_script_runs_on_an_empty_root(tmp_path, capsys):
    s = importlib.util.spec_from_file_location("audit_performance", "scripts/audit_performance.py"); mod = importlib.util.module_from_spec(s); s.loader.exec_module(mod)
    assert mod.main(["--root", str(tmp_path)]) == 0 and "Trades PAPER clos : 0" in capsys.readouterr().out
