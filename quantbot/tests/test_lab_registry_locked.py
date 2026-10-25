import json

import pandas as pd
import pytest

from quantbot.exceptions import MemoryStoreError
from quantbot.lab.locked import LockedSliceError, final_evaluation, split_locked
from quantbot.lab.registry import TrialRegistry, canonical_hash
from tests.helpers import planted_frame


def test_chain_verifies_and_detects_tampering(tmp_path):
    path = tmp_path / "reg.jsonl"
    reg = TrialRegistry(path)
    for i in range(4):
        reg.append("trial", {"spec_hash": f"s{i}", "data_hash": "d", "sharpe": 0.1 * i, "n_trades": 10})
    assert reg.verify() and TrialRegistry(path).n_trials() == 4  # rechargement
    lines = path.read_text().splitlines()
    forged = json.loads(lines[1]); forged["payload"]["sharpe"] = 9.9
    lines[1] = json.dumps(forged)
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(MemoryStoreError):
        TrialRegistry(path)


def test_deleting_a_line_is_detected(tmp_path):
    path = tmp_path / "reg.jsonl"
    reg = TrialRegistry(path)
    for i in range(3):
        reg.append("trial", {"spec_hash": f"s{i}", "data_hash": "d", "sharpe": 0.0, "n_trades": 1})
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(MemoryStoreError):
        TrialRegistry(path)


def test_identical_rerun_counts_once_but_variants_count():
    reg = TrialRegistry()
    assert reg.record_trial("spec", "data", 0.1, 50)
    assert not reg.record_trial("spec", "data", 0.1, 50)  # ré-exécution identique
    assert reg.record_trial("spec2", "data", 0.3, 50) and reg.record_trial("spec", "data2", 0.2, 50)
    assert reg.n_trials() == 3 and reg.var_sharpe() > 0


def test_canonical_hash_is_order_independent():
    assert canonical_hash({"a": 1, "b": [1, 2]}) == canonical_hash({"b": [1, 2], "a": 1})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_split_locked_geometry():
    df = planted_frame(3000)
    research, locked = split_locked(df, lock_months=12, min_frac=0.20)
    assert research.index[-1] < locked.lock_start
    assert (df.index[-1] - locked.lock_start) >= (df.index[-1] - df.index[0]) * 0.20 - pd.Timedelta(days=1)
    assert "close" not in repr(locked)  # le repr ne fuit aucune donnée


def test_locked_slice_read_once_per_spec_and_counts_as_trial():
    df = planted_frame(1500)
    _, locked = split_locked(df)
    reg = TrialRegistry()
    out = final_evaluation(locked, "specA", reg, lambda full, t0: {"n": len(full), "t0": str(t0)})
    assert out["n"] == 1500 and reg.locked_reads("specA") == 1 and reg.n_trials() == 1
    with pytest.raises(LockedSliceError):
        final_evaluation(locked, "specA", reg, lambda f, t: {})
    final_evaluation(locked, "specB", reg, lambda f, t: {})  # autre spec : permis, mais coûte un essai de plus
    assert reg.n_trials() == 2


def test_crash_during_locked_read_still_counts():
    _, locked = split_locked(planted_frame(1500))
    reg = TrialRegistry()

    def boom(full, t0):
        raise RuntimeError("crash")

    with pytest.raises(RuntimeError):
        final_evaluation(locked, "specC", reg, boom)
    assert reg.locked_reads("specC") == 1
    with pytest.raises(LockedSliceError):  # pas de 2e chance après un crash
        final_evaluation(locked, "specC", reg, lambda f, t: {})
