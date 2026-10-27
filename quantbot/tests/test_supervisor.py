import json
import sys
import time
from pathlib import Path

from quantbot.supervisor import Supervisor, default_workers, start_default

PY = sys.executable


def _wait(cond, t=10.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_crashing_worker_is_restarted_with_growing_backoff_and_status_is_written(tmp_path):
    sup = Supervisor(tmp_path, [("boom", [PY, "-c", "print('erreur MT5 injoignable'); raise SystemExit(3)"])], base_backoff=10.0, max_backoff=40.0)
    t0 = time.time(); sup.tick(t0)                                   # lancement
    w = sup.workers[0]; assert _wait(lambda: w.proc.poll() is not None)
    sup.tick(t0 + 1); assert w.state == "arrêté" and w.last_exit == 3 and w.restarts == 1 and 9.0 < w.next_start - (t0 + 1) <= 10.0 and w.backoff == 20.0
    sup.tick(t0 + 5); assert w.proc is None                          # pas encore l'heure
    sup.tick(t0 + 12); assert w.proc is not None                      # relancé
    assert _wait(lambda: w.proc.poll() is not None); sup.tick(t0 + 13); assert w.restarts == 2 and w.backoff == 40.0
    st = json.loads((tmp_path / "runtime" / "supervisor.json").read_text()); assert st["workers"][0]["last_exit"] == 3 and any("erreur MT5" in l for l in st["workers"][0]["tail"])


def test_stable_worker_resets_backoff_and_stop_terminates_children(tmp_path):
    sup = Supervisor(tmp_path, [("long", [PY, "-c", "import time; time.sleep(60)"])], base_backoff=10.0, stable_after=0.2)
    sup.tick(); w = sup.workers[0]; w.backoff = 160.0; time.sleep(0.4); sup.tick(); assert w.backoff == 10.0 and w.state == "en cours"
    pid = w.proc.pid; sup.stop(grace=5.0); assert w.proc.poll() is not None and sup.status()["workers"][0]["state"] == "arrêté"


def test_default_workers_run_only_paper_scripts_never_order_scripts(tmp_path):
    ws = default_workers(Path(tmp_path)); names = [n for n, _ in ws]; flat = " ".join(" ".join(a) for _, a in ws)
    assert names == ["paper_mt5", "paper_coinbase"] and "paper_all.py" in flat and "--source" in flat
    for forbidden in ("run_live", "order_send", "approve", "--live"):
        assert forbidden not in flat
    assert "apex_pullback_v1.json" in flat and "gold_quant_v1.json" in flat


def test_frozen_build_has_no_workers(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False); assert start_default(tmp_path) is None


def test_state_api_exposes_sync_and_supervisor_for_the_interface(tmp_path):
    from fastapi.testclient import TestClient
    from quantbot.gui.app import create_app
    (tmp_path / "runtime").mkdir(); (tmp_path / "runtime" / "supervisor.json").write_text(json.dumps({"workers": [{"name": "paper_mt5", "state": "arrêté"}]}))
    (tmp_path / "data").mkdir(); (tmp_path / "data" / "sync_status.json").write_text(json.dumps({"ts": time.time(), "results": []}))
    s = TestClient(create_app(tmp_path), base_url="http://127.0.0.1").get("/api/state").json()
    assert s["supervisor"]["workers"][0]["name"] == "paper_mt5" and s["sync"]["results"] == []
