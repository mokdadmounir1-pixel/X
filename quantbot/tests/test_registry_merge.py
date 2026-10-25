import importlib.util
from pathlib import Path

import pytest

from quantbot.lab.registry import TrialRegistry

S = Path(__file__).resolve().parents[1] / "scripts" / "registry_merge.py"
sp = importlib.util.spec_from_file_location("rm", S); rm = importlib.util.module_from_spec(sp); sp.loader.exec_module(rm)


def make(p, n):
    r = TrialRegistry(p)
    for i in range(n):
        r.record_trial(f"s{i}", "d", 0.1, 10)
    return r


def test_extension_is_accepted_and_history_is_preserved(tmp_path):
    cur, inc = tmp_path / "cur.jsonl", tmp_path / "inc.jsonl"
    make(cur, 3); inc.write_bytes(cur.read_bytes()); r = TrialRegistry(inc); r.record_trial("new", "d", 0.2, 10)
    assert "3 -> 4" in rm.merge(inc, cur) and TrialRegistry(cur).n_trials() == 4 and TrialRegistry(cur).verify()


def test_a_registry_that_dropped_or_rewrote_trials_is_refused(tmp_path):
    cur, other = tmp_path / "cur.jsonl", tmp_path / "other.jsonl"
    make(cur, 3); make(other, 5)                                    # historique différent (mêmes noms mais horodatages différents)
    before = cur.read_bytes()
    with pytest.raises(SystemExit, match="REFUS"):
        rm.merge(other, cur)
    assert cur.read_bytes() == before


def test_shorter_registry_is_refused(tmp_path):
    cur, short = tmp_path / "cur.jsonl", tmp_path / "short.jsonl"
    make(cur, 4); short.write_bytes(b"".join(cur.read_bytes().splitlines(True)[:2]))
    with pytest.raises(SystemExit, match="REFUS"):
        rm.merge(short, cur)
