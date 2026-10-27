import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quantbot.gui.app import create_app
from quantbot.ui import replay

ROOT = Path(__file__).resolve().parents[1]


def _root(tmp_path, with_real=True):
    (tmp_path / "specs").mkdir(); [shutil.copy(f, tmp_path / "specs") for f in (ROOT / "specs").glob("*.json")]
    if with_real and (ROOT / "data" / "real" / "XAUUSD_M15.csv").exists():
        (tmp_path / "data" / "real").mkdir(parents=True); [shutil.copy(ROOT / "data" / "real" / f, tmp_path / "data" / "real" / f) for f in ("XAUUSD_M15.csv", "EURUSD_M15.csv")]
    return tmp_path


def _crypto_csv(tmp_path, name="ZZZ-USD", n=60000):
    rng = np.random.default_rng(0); c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n))); o = np.r_[c[0], c[:-1]]; idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    d = tmp_path / "data" / "crypto"; d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"time": idx.strftime("%Y-%m-%d %H:%M:%S+00:00"), "open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999, "close": c, "volume": 100.0, "spread": 0.0, "spread_points": 0.0}).to_csv(d / f"{name}_M15.csv", index=False)


def test_strategy_list_exposes_all_specs_variants_and_every_available_instrument(tmp_path):
    r = _root(tmp_path); _crypto_csv(r); st = TestClient(create_app(r), base_url="http://127.0.0.1").get("/api/strategies").json()
    ids = {s["id"] for s in st["strategies"]}
    assert {"stop_hunt", "stop_hunt__sell", "stop_hunt__flip", "stop_hunt__buy", "apex_pullback", "mtf_confluence", "apex_levels", "gq_sweep", "smc_h1", "amd"} <= ids
    inst = {i["id"]: i for i in st["instruments_all"]}; assert "ZZZ-USD" in inst and inst["ZZZ-USD"]["origin"] == "crypto" and "exploration" in st["exploration_note"].lower()


@pytest.mark.skipif(not (ROOT / "data" / "real" / "EURUSD_M15.csv").exists(), reason="exports de recherche absents")
def test_a_gold_strategy_can_be_replayed_on_eurusd_in_exploration_mode_and_is_flagged(tmp_path):
    r = _root(tmp_path); c = TestClient(create_app(r), base_url="http://127.0.0.1")
    own = c.get("/api/strategy_replay", params={"instrument": "XAUUSD", "strategy": "gq_zrev", "bars": 3000}).json(); assert own["exploration"] is False
    ex = c.get("/api/strategy_replay", params={"instrument": "EURUSD", "strategy": "gq_zrev", "bars": 3000}); assert ex.status_code == 200
    j = ex.json(); assert j["exploration"] is True and "EXPLORATION" in j["note"] and j["metrics"]["n_trades"] >= 0 and j["data_origin"] == "real"


def test_crypto_instrument_replays_with_declared_crypto_costs_and_patterns_refuse_exploration(tmp_path):
    r = _root(tmp_path, with_real=False); _crypto_csv(r); c = TestClient(create_app(r), base_url="http://127.0.0.1")
    j = c.get("/api/strategy_replay", params={"instrument": "ZZZ-USD", "strategy": "gq_ema_pull", "bars": 3000}); assert j.status_code == 200 and j.json()["exploration"] and j.json()["data_origin"] == "crypto"
    bad = c.get("/api/strategy_replay", params={"instrument": "ZZZ-USD", "strategy": "patterns", "bars": 3000}); assert bad.status_code in (400, 409) and "spec" in bad.json()["detail"]
    miss = c.get("/api/strategy_replay", params={"instrument": "NOPE", "strategy": "gq_zrev", "bars": 3000}); assert miss.status_code in (400, 409) and "aucune donnée" in miss.json()["detail"]


def test_displayed_trial_budget_is_the_highest_declared_not_a_stale_one(tmp_path):
    r = _root(tmp_path, with_real=False); s = TestClient(create_app(r), base_url="http://127.0.0.1").get("/api/state").json(); assert s["status"]["trials_budget"] >= 120
