import json
from pathlib import Path

import pandas as pd
import pytest

from quantbot.exceptions import DataFetchError
from quantbot.live.approvals import check_approval, file_sha256
from quantbot.live.feed import BarFeed
from quantbot.live.runner import LiveRunner
from quantbot.live.state import StateStore
from tests.fake_mt5_live import FakeMT5Live

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "specs" / "inst_strategies_v1.json"


def approvals(tmp, strategy="vwap", instrument="XAUUSD", sha=None, by="Mounir", date="2026-10-26"):
    p = tmp / "approved_strategies.json"
    p.write_text(json.dumps({"approved": [{"id": strategy, "instrument": instrument, "spec": "specs/inst_strategies_v1.json",
                                           "spec_sha256": sha or file_sha256(SPEC), "approved_by": by, "date": date}]}), encoding="utf-8")
    return p


def runner(tmp, mt5, strategy="vwap", appr=None, **kw):
    return LiveRunner(mt5, "XAUUSD", strategy, SPEC, appr or (tmp / "absent.json"), tmp / "state.db", tmp / "KILL", **kw)


# ------------------------------------------------------------------------------------------ flux
def test_feed_drops_forming_bar_emits_each_bar_once_and_converts_clock():
    m = FakeMT5Live(n_bars=200)
    f = BarFeed(m, "XAUUSD", "M15", 500)
    df = f.poll()
    assert len(df) == 200 and df.index.is_monotonic_increasing                      # 201 barres, la dernière (en formation) écartée
    assert df["close"].iloc[-1] == m.bars[-2]["close"] and m.bars[-1]["close"] not in df["close"].tolist()[-1:]
    assert f.new_bars(df) == []                                                      # démarrage : la dernière barre est de l'histoire, aucune décision dessus
    assert f.poll() is None                                                          # aucune nouvelle barre : rien
    m.advance(2)
    df2 = f.poll()
    assert [t for t in f.new_bars(df2)] == list(df2.index[-2:])                      # exactement 2 nouvelles barres, dans l'ordre
    # horloge : 2024-06 (été) = UTC+3 => UTC = courtier - 3 h
    first = pd.Timestamp(m.bars[0]["time"], unit="s")
    assert df.index[0] == first - pd.Timedelta(hours=3) or df.index[0] == first - pd.Timedelta(hours=2)


def test_feed_flags_stale_stream_and_holes_and_unknown_timeframe():
    m = FakeMT5Live(n_bars=100)
    clock = [0.0]
    f = BarFeed(m, "XAUUSD", "M15", 500, stale_after_s=600, clock=lambda: clock[0])
    f.new_bars(f.poll())
    clock[0] = 1000.0
    assert f.poll() is None and f.status.stale                                       # flux figé détecté
    for b in m.bars[60:]:
        b["time"] += 3600 * 24 * 9                                                   # trou de 9 jours
    f2 = BarFeed(m, "XAUUSD", "M15", 500)
    f2.poll()
    assert f2.status.hole is not None and f2.status.hole[1] > 120
    with pytest.raises(DataFetchError):
        BarFeed(m, "XAUUSD", "M7", 10)


def test_feed_failure_is_an_error_not_a_silent_empty_frame():
    m = FakeMT5Live(); m.copy_rates_from_pos = lambda *a: None
    with pytest.raises(DataFetchError):
        BarFeed(m, "XAUUSD", "M15", 100).poll()


# ------------------------------------------------------------------------------------- approbation
def test_approval_requires_signed_entry_matching_spec_hash_and_instrument(tmp_path):
    ok, why = check_approval("vwap", "XAUUSD", SPEC, approvals(tmp_path))
    assert ok and "Mounir" in why
    assert not check_approval("vwap", "XAUUSD", SPEC, tmp_path / "absent.json")[0]
    assert not check_approval("amd", "XAUUSD", SPEC, approvals(tmp_path))[0]                      # autre stratégie
    assert not check_approval("vwap", "EURUSD", SPEC, approvals(tmp_path))[0]                     # autre instrument
    assert not check_approval("vwap", "XAUUSD", SPEC, approvals(tmp_path, sha="0" * 64))[0]       # spec modifiée
    assert not check_approval("vwap", "XAUUSD", SPEC, approvals(tmp_path, by=""))[0]              # sans signataire
    bad = tmp_path / "bad.json"; bad.write_text("{pas du json")
    assert not check_approval("vwap", "XAUUSD", SPEC, bad)[0]


# ----------------------------------------------------------------------------------------- boucle
def test_unapproved_strategy_runs_in_observation_and_never_touches_order_api(tmp_path):
    m = FakeMT5Live(n_bars=1500)
    r = runner(tmp_path, m)
    assert r.setup() == "OBSERVATION"
    for _ in range(300):
        m.advance(1); r.step()
    assert m.sent == [] and m.checked == [] and m.positions == []                    # ZÉRO appel d'ordre
    assert r.state.get("mode") == "OBSERVATION" and "non approuvée" in r.state.get("why") or "absent" in r.state.get("why")


def test_approved_strategy_with_active_kill_file_starts_in_observation(tmp_path):
    (tmp_path / "KILL").write_text("stop")
    m = FakeMT5Live(n_bars=1500)
    r = runner(tmp_path, m, appr=approvals(tmp_path))
    assert r.setup() == "OBSERVATION" and "coupe-circuit" in r.state.get("why")
    for _ in range(50):
        m.advance(1); r.step()
    assert m.sent == []


def test_modified_spec_hash_downgrades_to_observation(tmp_path):
    m = FakeMT5Live(n_bars=1500)
    r = runner(tmp_path, m, appr=approvals(tmp_path, sha="f" * 64))
    assert r.setup() == "OBSERVATION" and "spec" in r.state.get("why")


def test_non_demo_account_cannot_become_active(tmp_path):
    from quantbot.exceptions import LiveTradingDisabledError
    m = FakeMT5Live(n_bars=1500, demo=False)
    r = runner(tmp_path, m, appr=approvals(tmp_path))
    with pytest.raises(LiveTradingDisabledError):
        r.setup()
    assert m.sent == []


class OneShotSignal:
    """DOUBLE DE TEST : émet UN signal à la 3e évaluation. Sert à exercer la mécanique d'ordre ; ne simule PAS un marché."""

    def __init__(self):
        self.n = 0

    def evaluate(self, window, htf=None):
        from quantbot.patterns.base import PatternMatch
        from quantbot.signals.engine import Signal
        self.n += 1
        if self.n != 3:
            return None
        px = float(window["close"].iloc[-1])
        return Signal("bullish", 0.9, px, 1.0, window.index[-1], [PatternMatch("t", "event", "bullish", 0.9, 0, 1)],
                      stop_price=px - 5.0, take_profit_price=px + 10.0)


def test_approved_demo_order_path_is_checked_staged_levelled_and_restart_safe(tmp_path):
    m = FakeMT5Live(n_bars=1500)
    appr = approvals(tmp_path, strategy="fvg_h1")
    r = runner(tmp_path, m, strategy="fvg_h1", appr=appr)
    assert r.setup() == "DEMO_ACTIF"
    r.engine.signals = OneShotSignal()
    for _ in range(12):
        m.advance(1); r.step()
    opens = [q for q in m.sent if "position" not in q]
    assert len(opens) == 1 and len(m.checked) >= 1                                          # un seul ordre, vérifié avant envoi
    assert opens[0]["sl"] > 0 and opens[0]["tp"] > 0 and opens[0]["comment"].startswith("qb:")
    assert m.checked[0]["comment"] == opens[0]["comment"]
    assert len(m.positions) == 1 and r.engine.broker.position is not None
    n_sent = len(m.sent)
    r2 = runner(tmp_path, m, strategy="fvg_h1", appr=appr)                                 # REDÉMARRAGE
    assert r2.setup() == "DEMO_ACTIF"
    assert len(m.sent) == n_sent and len(m.positions) == 1                                  # rien rejoué, rien doublé
    assert r2.engine.broker.position is not None and r2.engine.broker.position.side == "long"   # position adoptée


def test_unexpected_exception_trips_kill_switch_and_blocks_all_orders(tmp_path):
    m = FakeMT5Live(n_bars=1500)
    r = runner(tmp_path, m, strategy="fvg_h1", appr=approvals(tmp_path, strategy="fvg_h1"))
    r.setup()
    r.step()  # amorçage : la barre de démarrage n'est pas émise
    r.engine.on_bar = lambda df: (_ for _ in ()).throw(RuntimeError("bug"))
    m.advance(1)
    assert r.step() == "crash" and r.kill.active()
    assert any(e["kind"] == "exception_inattendue" for e in r.state.recent_events(5))
    before = len(m.sent)
    m.advance(3); r.step()
    assert len(m.sent) == before


def test_run_forever_stops_cleanly_on_keyboard_interrupt(tmp_path):
    m = FakeMT5Live(n_bars=1500)
    r = runner(tmp_path, m, sleep=lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))
    r.setup()
    r.run_forever(poll_s=0)
    assert any(e["kind"] == "arret" for e in r.state.recent_events(5))
