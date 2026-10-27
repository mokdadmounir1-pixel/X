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
    other = {m["id"]: m for m in c["other_modules"]}; assert "carnet" in other["ofi_lob"]["status"] and "options" in other["vol_arb"]["status"]
    assert "0 PASS" in c["note"]
