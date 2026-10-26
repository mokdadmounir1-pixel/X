import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace as NS

from tests.fake_mt5_live import FakeMT5Live

S = importlib.util.spec_from_file_location("preflight", Path(__file__).resolve().parents[1] / "scripts" / "preflight.py"); pf = importlib.util.module_from_spec(S); S.loader.exec_module(pf)


class Mt5(FakeMT5Live):
    def __init__(self, connected=True, init=True, tick_age=5.0, **kw):
        super().__init__(**kw); self._c, self._i, self._age = connected, init, tick_age
    def initialize(self, *a, **k): return self._i
    def terminal_info(self): return NS(connected=self._c, trade_allowed=True)
    def symbol_info_tick(self, s): return NS(bid=2000.0, ask=2000.08, time=pf.time.time() - self._age)


def levels(res): return {r["what"].split(" ")[0] + str(i): r["level"] for i, r in enumerate(res)}


def test_ready_when_demo_connected_and_fresh_quotes(tmp_path):
    res = pf.run(tmp_path, mt5=Mt5(), port=65001)
    assert not [r for r in res if r["level"] == pf.BLOCK and "specs" not in r["what"]] and any("DÉMO" in r["what"] for r in res)
    assert all("1234" not in r["what"] for r in res)                                     # login masqué


def test_every_blocker_explains_what_to_do(tmp_path):
    for m in (Mt5(init=False), Mt5(connected=False), Mt5(demo=False)):
        res = pf.run(tmp_path, mt5=m, port=65001); blk = [r for r in res if r["level"] == pf.BLOCK and "specs" not in r["what"]]
        assert blk and all(r["fix"] for r in blk)


def test_stale_quote_is_a_warning_not_a_blocker_and_main_exit_codes(tmp_path, capsys):
    res = pf.run(tmp_path, mt5=Mt5(tick_age=4000.0), port=65001); assert any(r["level"] == pf.WARN and "cotation" in r["what"] for r in res)
    (tmp_path / "specs").mkdir(); (tmp_path / "specs" / "a.json").write_text("{}")
    assert pf.main(["--root", str(tmp_path)], mt5=Mt5(), port=65001) == 0 and "PRÊT" in capsys.readouterr().out
    assert pf.main(["--root", str(tmp_path)], mt5=Mt5(init=False), port=65001) == 1


def test_preflight_never_sends_orders(tmp_path):
    m = Mt5(); pf.run(tmp_path, mt5=m, port=65001); assert m.sent == [] and m.checked == []


def test_one_click_launcher_runs_preflight_first_and_never_touches_orders():
    root = Path(__file__).resolve().parents[1]; bat = (root / "lancer_tout.bat").read_text(encoding="utf-8"); allb = bat + (root / "scripts" / "start_all.bat").read_text(encoding="utf-8")
    assert bat.index("preflight.py") < bat.index("start_all.bat") and "errorlevel 1" in bat
    for forbidden in ("order_send", "run_live", "--live", "DEMO_ACTIF", "approve"):
        assert forbidden not in allb
