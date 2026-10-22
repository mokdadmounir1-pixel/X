import json, time, urllib.request, urllib.error
import pytest
from ftmo_algo.engine.guardian import PropProfile
from ftmo_algo.engine.sim import SimConfig
from ftmo_algo.live.agent import Agent
from ftmo_algo.live.runner import Runner
from ftmo_algo.dashboard.server import serve
from ftmo_algo.dashboard import jobs


class Feed:
    mode = "DEMO"
    def next(self): return "WAIT"
    def stale(self, *a): return False


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prof = PropProfile()
    ag = Agent("a", "session_orb", None, ["US500"], prof, SimConfig())
    r = Runner([ag], Feed(), label="SYNTHÉTIQUE", profile=prof)
    r.evo_dir = str(tmp_path / "res")
    s = serve(r, 8793, block=False)
    yield r, tmp_path
    s.shutdown()


def call(path, body=None, headers=None, raw=None, method="POST"):
    h = {"Content-Type": "application/json"}
    h.update(headers if headers is not None else {"X-Requested-With": "dashboard"})
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request("http://127.0.0.1:8793" + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as f:
            return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_actions_refuse_foreign_requests(srv):
    r, _ = srv
    assert call("/api/control", {"pause": True}, headers={})[0] == 403              # sans en-tête
    assert call("/api/control", {"pause": True}, headers={"X-Requested-With": "dashboard", "Origin": "http://evil.example"})[0] == 403
    assert not r.paused
    assert call("/api/control", {"pause": True})[0] == 200 and r.paused


def test_agent_stop_and_restart(srv):
    r, _ = srv
    assert call("/api/control", {"agent": "a", "paused": True})[0] == 200
    assert r.agents[0].paused and "manuel" in r.agents[0].pause_reason
    assert call("/api/control", {"agent": "a", "paused": False})[0] == 200 and not r.agents[0].paused
    assert call("/api/control", {"agent": "zzz", "paused": True})[0] == 400


def test_profit_lock_set_validate_persist_disable(srv):
    r, tmp = srv
    c, j = call("/api/control", {"profit_lock": {"day_gain_pct": 2.0, "arm_pct": 1.0, "giveback_frac": 0.5}})
    assert c == 200 and r.agents[0].sim.g.p.profit_lock["day_gain_pct"] == 2.0
    assert json.loads((tmp / "res" / "dashboard_settings.json").read_text())["profit_lock"]["arm_pct"] == 1.0
    assert call("/api/control", {"profit_lock": {"giveback_frac": 0.5}})[0] == 400        # sans armement
    assert call("/api/control", {"profit_lock": {"day_gain_pct": 99}})[0] == 400
    assert call("/api/control", {"profit_lock": {}})[0] == 200 and not r.agents[0].sim.g.p.profit_lock
    assert r.state()["profit_lock"] == {}


def test_upload_validates_name_and_saves(srv):
    _, tmp = srv
    assert call("/api/upload?name=../x.csv", raw=b"a,b\n1,2\n", headers={"X-Requested-With": "dashboard"})[0] == 400
    assert call("/api/upload?name=EURUSD_M5.txt", raw=b"x", headers={"X-Requested-With": "dashboard"})[0] == 400
    c, j = call("/api/upload?name=EURUSD_M5.csv", raw=b"time,open\n1,2\n", headers={"X-Requested-With": "dashboard"})
    assert c == 200 and (tmp / "data" / "EURUSD_M5.csv").read_bytes().startswith(b"time")
    assert any(f["name"] == "EURUSD_M5.csv" for f in call("/api/meta", method="GET")[1]["files"])


def test_job_params_are_validated_no_shell():
    ok = ["session_orb"]; ins = {"US500", "EURUSD"}
    with pytest.raises(jobs.JobError): jobs.build_argv("rm -rf", {}, "o", ok, ins)
    with pytest.raises(jobs.JobError): jobs.build_argv("research", {"instruments": "US500;ls"}, "o", ok, ins)
    with pytest.raises(jobs.JobError): jobs.build_argv("research", {"instruments": "FOO"}, "o", ok, ins)
    with pytest.raises(jobs.JobError): jobs.build_argv("research", {"algos": "evil"}, "o", ok, ins)
    with pytest.raises(jobs.JobError): jobs.build_argv("research", {"workers": 9999}, "o", ok, ins)
    a = jobs.build_argv("evolve", {"instruments": "US500", "algos": "session_orb", "loop": True, "lock_exit": True}, "o", ok, ins)
    assert "--loop" in a and "--lock-exit" in a and a[3] == "evolve" and ";" not in " ".join(a)


def test_job_runs_to_completion_and_is_listed(srv):
    c, j = call("/api/job/start", {"kind": "data-check", "params": {"instruments": "US500", "years": 0.5, "workers": 1}})
    assert c == 200
    jid = j["id"]
    for _ in range(120):
        lst = call("/api/jobs?id=" + jid, method="GET")[1]
        st = [x for x in lst["jobs"] if x["id"] == jid][0]["status"]
        if st != "en cours":
            break
        time.sleep(0.5)
    assert st == "terminée" and "SYNTHÉTIQUE" in lst["log"]
    assert call("/api/job/start", {"kind": "research", "params": {"instruments": "NOPE"}})[0] == 400


def test_job_can_be_stopped(srv):
    c, j = call("/api/job/start", {"kind": "install", "params": {"only": "numpy"}})   # longue tâche arrêtable
    assert c == 200 and call("/api/job/stop", {"id": j["id"]})[0] == 200
    for _ in range(40):
        st = [x for x in call("/api/jobs", method="GET")[1]["jobs"] if x["id"] == j["id"]][0]["status"]
        if st != "en cours":
            break
        time.sleep(0.5)
    assert st in ("arrêtée", "terminée", "échec")
