import importlib.util
import json
import time
from pathlib import Path

from quantbot.live.state import StateStore
from quantbot.supervisor import NOT_LAUNCHED, PAPER_SPECS

ROOT = Path(__file__).resolve().parents[1]
sp = importlib.util.spec_from_file_location("caa", ROOT / "scripts" / "check_all_active.py"); caa = importlib.util.module_from_spec(sp); sp.loader.exec_module(caa)
S = importlib.util.spec_from_file_location("paper_all2", ROOT / "scripts" / "paper_all.py"); pa = importlib.util.module_from_spec(S); S.loader.exec_module(pa)


def test_every_spec_with_strategies_is_launched_or_explicitly_excluded_with_a_reason():
    launched = {Path(p).stem for p in PAPER_SPECS}
    for f in sorted((ROOT / "specs").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8")); st = d.get("strategies")
        if isinstance(st, dict) and st:
            assert f.stem in launched or f.stem in NOT_LAUNCHED, f"{f.stem} : stratégies jamais lancées et sans raison déclarée"
    assert all(len(v) > 20 for v in NOT_LAUNCHED.values()) and not (launched & set(NOT_LAUNCHED) - {"crypto_paper_v1"})
    assert all((ROOT / p).is_file() for p in PAPER_SPECS) and len(PAPER_SPECS) == len(set(PAPER_SPECS))


def test_start_all_bat_lists_the_same_specs_as_the_supervisor():
    bat = (ROOT / "scripts" / "start_all.bat").read_text(encoding="utf-8")
    for p in PAPER_SPECS:
        assert Path(p).name.replace("/", "\\") in bat, p


def test_duplicate_strategy_on_two_specs_is_launched_once_first_spec_wins():
    specs = [("a", json.loads((ROOT / "specs" / "candidates_v1b.json").read_text(encoding="utf-8"))), ("b", json.loads((ROOT / "specs" / "candidates_v1.json").read_text(encoding="utf-8")))]
    seen, got = set(), []
    for name, sp_ in specs:
        pairs = [c for c in pa.combos(sp_) if c not in seen]; seen.update(pairs); got.append((name, pairs))
    assert all(n in ("ibs_reversion", "rsi2_reversion") for _, n in got[0][1]) and not [p for p in got[1][1] if p[1] in ("ibs_reversion", "rsi2_reversion")] and got[1][1]


def test_expected_list_has_no_duplicates_and_check_reports_missing_and_alive(tmp_path):
    exp = caa.expected(ROOT); keys = [(e["source"], e["instrument"], e["strategy"]) for e in exp]; assert len(keys) == len(set(keys)) and len(exp) > 100
    assert {"orb_stocks_in_play"} .isdisjoint({e["strategy"] for e in exp}) and any(e["strategy"] == "apex_levels" for e in exp) and any(e["strategy"] == "ibs_reversion" and e["spec"] == "candidates_v1b" for e in exp)
    (tmp_path / "runtime" / "paper").mkdir(parents=True); s = StateStore(tmp_path / "runtime" / "paper" / "XAUUSD_apex_levels.db"); s.set("heartbeat", time.time())
    assert caa.state(tmp_path, "XAUUSD", "apex_levels", time.time()) == "VIVANT" and caa.state(tmp_path, "XAUUSD", "x", time.time()) == "ABSENT"
    s.set("heartbeat", time.time() - 500); assert caa.state(tmp_path, "XAUUSD", "apex_levels", time.time()) == "ARRETE"
