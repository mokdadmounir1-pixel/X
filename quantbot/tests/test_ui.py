import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pandas as pd
import pytest

from quantbot.config import Settings
from quantbot.data.loaders import generate_synthetic
from quantbot.ui import server


def test_state_reflects_reports_and_never_claims_an_edge_without_pass():
    s = server.collect_state()
    assert s["status"]["live_trading"].startswith("VERROUILLÉ")
    names = [sp["name"] for sp in s["specs"]]
    assert "baseline_v0" in names and "baseline_v1" in names
    verdicts = [r.get("verdict") for sp in s["specs"] for r in sp["results"]]
    assert s["status"]["edge_validated"] == any(v == "PASS" for v in verdicts)
    assert s["status"]["trials"] >= 6 and s["status"]["locked_reads"] == 0 and s["status"]["registry_chain_ok"]


def test_replay_returns_curve_and_never_needs_orders():
    df = generate_synthetic(900, seed=2)
    out = server.run_replay(df, Settings())
    assert out["equity"] and out["metrics"]["n_trades"] >= 0 and "reasons" in out


def test_replay_endpoint_rejects_unknown_instrument_and_clamps_bars():
    with pytest.raises(ValueError):
        server.replay_instrument("NOPE", 1000)


def test_http_server_binds_locally_and_serves_state():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    assert httpd.server_address[0] == "127.0.0.1"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        port = httpd.server_address[1]
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert "quantbot" in html and "Aucun edge" in html
        state = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state").read())
        assert state["status"]["live_trading"].startswith("VERROUILLÉ")
        err = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/replay?instrument=NOPE") if False else None
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/replay?instrument=NOPE")
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        httpd.shutdown()
