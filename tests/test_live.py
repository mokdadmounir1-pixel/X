import json, threading, time, urllib.request
import numpy as np
import pytest
from ftmo_algo.engine.guardian import PropProfile
from ftmo_algo.engine.sim import SimConfig
from ftmo_algo.live.agent import Agent
from ftmo_algo.live.runner import Runner, KillSwitch, Notifier


class StaleFeed:
    mode = "DEMO"
    def next(self): return "WAIT"
    def stale(self, *a): return True


def test_frozen_feed_pauses_agents_and_alerts():
    prof = PropProfile()
    ag = Agent("a", "session_orb", None, ["US500"], prof, SimConfig())
    r = Runner([ag], StaleFeed(), label="DÉMO", profile=prof)
    r.step()
    assert not r.flux_ok and ag.paused and "flux" in ag.pause_reason
    assert any(n["level"] == "alert" for n in r.notifier.items)
    st = r.state()
    assert st["flux_ok"] is False


def test_killswitch_pauses_agent_when_live_performance_leaves_mc_interval():
    prof = PropProfile()
    ag = Agent("a", "session_orb", None, ["US500"], prof, SimConfig())
    rng = np.random.default_rng(0)
    ks = KillSwitch({"a": rng.normal(0.3, 1.0, 300)})
    ag.sim.trades = [{"r": -1.0, "exit_t": i, "pnl": -1} for i in range(25)]       # 25 pertes d'affilée
    assert "Monte Carlo" in (ks.check(ag) or "")
    ag.sim.trades = [{"r": 0.3, "exit_t": i, "pnl": 1} for i in range(25)]
    assert ks.check(ag) is None


def test_real_account_gate_never_automatic():
    from ftmo_algo.live.gate import real_account_conditions
    c = real_account_conditions("PASS", 0.2, 5, 40, 0.1)
    assert c["toutes_remplies"] and "HUMAINE" in c["action"]
    assert not real_account_conditions("WATCH", 0.2, 5, 40, 0.1)["toutes_remplies"]
    assert not real_account_conditions("PASS", -0.1, 5, 40, 0.1)["toutes_remplies"]
    assert not real_account_conditions("PASS", 0.2, 2, 40, 0.1)["toutes_remplies"]


def test_dashboard_page_renders_without_js_error_and_shows_flux_alert():
    pw = pytest.importorskip("playwright.sync_api")
    import os
    from ftmo_algo.dashboard.server import serve
    prof = PropProfile()
    ag = Agent("a", "session_orb", None, ["US500"], prof, SimConfig())
    r = Runner([ag], StaleFeed(), label="SYNTHÉTIQUE", profile=prof)
    r.step()                                     # flux figé -> alerte rouge
    srv = serve(r, 8791, block=False)
    exe = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
    if not os.path.exists(exe):
        pytest.skip("chromium absent")
    errs = []
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        pg = b.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto("http://127.0.0.1:8791"); pg.wait_for_timeout(2500)
        assert pg.is_visible("#alert") and "INTERROMPU" in pg.inner_text("#alert")
        assert "SYNTH" in pg.inner_text("#badge")
        b.close()
    srv.shutdown()
    assert errs == [], errs
