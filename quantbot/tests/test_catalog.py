import pytest
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from quantbot.gui.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_lists_every_executable_strategy_with_research_verdict_and_missing_modules(tmp_path):
    (tmp_path / "specs").mkdir(); [shutil.copy(f, tmp_path / "specs") for f in (ROOT / "specs").glob("*.json")]
    if (ROOT / "reports").exists():
        shutil.copytree(ROOT / "reports", tmp_path / "reports", ignore=shutil.ignore_patterns("*.log", "dataset.csv", "daily_R.csv"))
    c = TestClient(create_app(tmp_path), base_url="http://127.0.0.1").get("/api/catalog").json()
    ids = {r["id"] for r in c["strategies"]}
    assert {"apex_pullback", "mtf_confluence", "cta_donchian", "il_svr", "stop_hunt", "stop_hunt__sell", "stop_hunt__flip", "stop_hunt__buy", "gq_sweep", "apex_levels", "smc_h1"} <= ids and c["n_strategies"] >= 25
    cta = next(r for r in c["strategies"] if r["id"] == "cta_donchian")
    assert cta["code"] == "CTA_DONCHIAN_H4" and cta["family"] == "Suivi de tendance" and cta["paper"]["running"] is False
    if (ROOT / "reports" / "cta_donchian_v1").exists():
        assert cta["research"][0]["verdict"] == "FAIL" and cta["research"][0]["gates_failed"] == ["null_test"]
    other = {m["id"]: m for m in c["other_modules"]}; assert "chaîne" in other["vol_arb"]["status"] and "tail_dependence" in other; assert any(r["id"] == "ofi_depth" and r["data_missing"] is not None for r in c["strategies"])
    assert "0 PASS" in c["note"]


def test_replay_on_too_short_history_gives_readable_error_not_internal_error(tmp_path):
    import shutil
    import numpy as np, pandas as pd
    from quantbot.ui import replay
    shutil.copytree(ROOT / "specs", tmp_path / "specs")
    n = 3000; i = pd.date_range("2026-08-01", periods=n, freq="15min"); c = 100 + np.cumsum(np.random.default_rng(0).normal(0, .1, n))
    d = tmp_path / "data" / "crypto"; d.mkdir(parents=True)
    pd.DataFrame({"time": i.strftime("%Y-%m-%d %H:%M:%S+00:00"), "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1.0}).to_csv(d / "ETH-USD_M15.csv", index=False)
    with pytest.raises(FileNotFoundError, match="AVANT la période verrouillée"):
        replay.run_strategy_replay("ETH-USD", 12000, "apex_pullback", "recherche", tmp_path)
