import json
from pathlib import Path

import pytest

from quantbot.config import Settings
from quantbot.lab.gates import GateCfg

ROOT = Path(__file__).resolve().parents[1]
SPECS = {n: json.loads((ROOT / "specs" / f"{n}.json").read_text(encoding="utf-8")) for n in ("baseline_v0", "baseline_v1")}
SPEC = SPECS["baseline_v0"]
PROV = json.loads((ROOT / "data" / "real" / "PROVENANCE.json").read_text(encoding="utf-8"))


def test_spec_hashes_match_provenance_manifest():
    declared = {i["file"]: i["sha256"] for i in PROV["instruments"]}
    assert SPEC["data_sha256"] == declared
    assert PROV["synthetic"] is False and PROV["orders_sent"] == 0


def test_spec_settings_and_gates_are_valid_and_current():
    Settings.from_dict({**SPEC["settings"]})  # lève ConfigError si la spec est invalide
    assert GateCfg(**SPEC["gates"]) == GateCfg()  # les seuils préenregistrés = ceux du code


def test_every_instrument_has_a_declared_cost_basis_and_none_is_free():
    assert set(SPEC["costs"]) - {"_note"} == set(SPEC["instruments"])
    for name in SPEC["instruments"]:
        c = SPEC["costs"][name]
        assert c["basis"] and c["slippage"] > 0  # un coût de glissement nul n'est jamais supposé
        assert c["spread_frac"] is None or c["spread_frac"] > 0


def test_baseline_script_refuses_unknown_spread():
    import importlib.util
    spec = importlib.util.spec_from_file_location("baseline_real", ROOT / "scripts" / "baseline_real.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bad = json.loads(json.dumps(SPEC)); bad["costs"]["XAUUSD"]["spread_frac"] = None
    with pytest.raises(SystemExit):
        mod.build_settings(bad, "XAUUSD", {"spread_frac": None, "reliable": False})
    ok = mod.build_settings(bad, "XAUUSD", {"spread_frac": 2e-5, "reliable": True})
    assert ok.execution.spread == 2e-5


def test_v1_declares_its_motivation_and_keeps_costs_and_hypothesis_identical():
    v0, v1 = SPECS["baseline_v0"], SPECS["baseline_v1"]
    assert v1["parent"] == "baseline_v0" and "DÉFAUT DE RISQUE" in v1["change_reason"]
    assert v1["costs"] == v0["costs"] and v1["instruments"] == v0["instruments"] and v1["data_sha256"] == v0["data_sha256"]
    assert v1["settings"]["signals"]["atr_floor_frac"] == 0.5 and v1["settings"]["risk"]["flat_before_weekend"] is True
    assert Settings.from_dict(v1["settings"]).risk.flat_before_weekend
    assert GateCfg(**v1["gates"]) == GateCfg()


def test_gold_scalp_spec_respects_the_user_rule_no_timeframe_above_h1_for_signals():
    spec = json.loads((ROOT / "specs" / "gold_scalp_v1.json").read_text(encoding="utf-8"))
    assert set(spec["timeframes"]) == {"M1", "M3", "M15", "H1"}          # jamais H4/D1 comme timeframe de SIGNAL
    assert set(spec["instruments"]) == {"XAUUSD"}
    s = Settings.from_dict(spec["settings"])
    assert s.risk.max_cost_r == 0.15 and (s.risk.session_utc_start, s.risk.session_utc_end) == (7, 17) and s.risk.flat_before_weekend
    assert spec["costs"]["XAUUSD"]["slippage"] > 0 and spec["costs"]["XAUUSD"]["basis"]
    for tf, c in spec["timeframes"].items():
        assert c["max_hold_bars"] <= 30 and ("file" in c or c.get("rule") in (None, "1h"))
