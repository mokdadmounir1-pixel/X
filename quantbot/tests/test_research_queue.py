import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("research_queue", ROOT / "scripts" / "research_queue.py")
rq = importlib.util.module_from_spec(spec); spec.loader.exec_module(rq)


def project(tmp, items, budget=60, trials=0):
    (tmp / "specs").mkdir(); (tmp / "reports").mkdir(); (tmp / "scripts").mkdir()
    (tmp / "specs" / "queue.json").write_text(json.dumps({"budget": budget, "items": items}))
    from quantbot.lab.registry import TrialRegistry
    r = TrialRegistry(tmp / "reports" / "registry.jsonl")
    for i in range(trials):
        r.record_trial(f"s{i}", "d", 0.1, 10)
    return tmp


ITEM = {"id": "a", "script": "optimize", "spec": "specs/a.json", "expected_trials": 3}


def test_runs_each_item_once_and_records_it(tmp_path):
    root = project(tmp_path, [ITEM]); calls = []
    run = lambda cmd, **k: calls.append(cmd) or NS(returncode=0)
    ok = lambda r, s: (True, "")
    s1 = rq.run_once(root, run, ok); s2 = rq.run_once(root, run, ok)
    assert s1["ran"]["id"] == "a" and s2["ran"] is None and len(calls) == 1


def test_uncommitted_spec_is_blocked(tmp_path):
    root = project(tmp_path, [ITEM]); calls = []
    s = rq.run_once(root, lambda *a, **k: calls.append(1) or NS(returncode=0), lambda r, sp: (False, "spec non commitée"))
    assert not calls and "a" in s["blocked"]


def test_budget_blocks_item_instead_of_overrunning(tmp_path):
    root = project(tmp_path, [ITEM], budget=10, trials=9); calls = []
    s = rq.run_once(root, lambda *a, **k: calls.append(1) or NS(returncode=0), lambda r, sp: (True, ""))
    assert not calls and "budget" in s["blocked"]["a"]


def test_scripts_outside_the_whitelist_never_run(tmp_path):
    bad = {**ITEM, "id": "b", "script": "baseline_real"}                   # celui-ci sait lire la période verrouillée
    root = project(tmp_path, [bad]); calls = []
    s = rq.run_once(root, lambda *a, **k: calls.append(1) or NS(returncode=0), lambda r, sp: (True, ""))
    assert not calls and "non autorisé" in s["blocked"]["b"]
    assert "baseline_real" not in rq.ALLOWED and "--locked" not in " ".join(rq.ALLOWED)


def test_real_git_check_rejects_untracked_and_dirty_files(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    f = tmp_path / "specs"; f.mkdir(); p = f / "a.json"; p.write_text("{}")
    assert rq.spec_is_committed(tmp_path, p)[0] is False                      # non suivie
    subprocess.run(["git", "add", "."], cwd=tmp_path)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"], cwd=tmp_path)
    assert rq.spec_is_committed(tmp_path, p) == (True, "")
    p.write_text('{"x":1}')
    assert rq.spec_is_committed(tmp_path, p)[0] is False                      # modifiée depuis le commit
