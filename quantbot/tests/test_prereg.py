import json
from pathlib import Path

import pytest

from quantbot.config import Settings
from quantbot.lab.gates import GateCfg

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "specs" / "baseline_v0.json").read_text(encoding="utf-8"))
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
