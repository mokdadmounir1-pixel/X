import json
import pytest
from nexus.registry import ExperimentRegistry

BASE = dict(hypothesis="h", data_ref="d@sha", code_ref="c@sha", params={"a": 1},
            costs={"c": 1}, dates={"s": "2020", "e": "2021"}, status="SYNTHETIQUE")


def test_chain_ok_and_counts_negatives(tmp_path):
    r = ExperimentRegistry(tmp_path / "r.jsonl")
    r.record(**BASE, outcome="negative", family="f1")
    r.record(**BASE, outcome="positive", family="f1")
    assert r.verify() == (True, "ok")
    assert r.n_trials("f1") == 2


def test_missing_field_rejected(tmp_path):
    r = ExperimentRegistry(tmp_path / "r.jsonl")
    with pytest.raises(ValueError):
        r.record(hypothesis="x")


def test_tamper_detected(tmp_path):
    p = tmp_path / "r.jsonl"
    r = ExperimentRegistry(p)
    for _ in range(3):
        r.record(**BASE, outcome="negative")
    lines = p.read_text().splitlines()
    d = json.loads(lines[1]); d["body"]["outcome"] = "positive"
    lines[1] = json.dumps(d)
    p.write_text("\n".join(lines) + "\n")
    assert not r.verify()[0]


def test_deletion_detected(tmp_path):
    p = tmp_path / "r.jsonl"
    r = ExperimentRegistry(p)
    for _ in range(3):
        r.record(**BASE)
    lines = p.read_text().splitlines()
    p.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert not r.verify()[0]
