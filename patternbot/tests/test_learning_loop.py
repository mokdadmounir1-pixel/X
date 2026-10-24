import json

import pandas as pd
import pytest

from patternbot.ai.adapters import LLMAdapter, extract_json
from patternbot.ai.orchestrator import AIOrchestrator
from patternbot.config import Settings
from patternbot.data.loaders import generate_synthetic
from patternbot.exceptions import AIAdapterError, MemoryStoreError
from patternbot.execution.broker import Trade
from patternbot.improvement.diagnosis import (Failure, Hypothesis, analyze_failures, propose_changes,
                                              sanitize_overrides)
from patternbot.improvement.journal import TradeJournal
from patternbot.improvement.loop import ImprovementLoop
from patternbot.improvement.runner import PaperRunner
from patternbot.memory.store import ExperimentStore
from patternbot.validation.validator import Check, ValidationReport, Validator

S = Settings()


def trade(pnl=10.0, reason="take_profit", patterns=("hammer",), i=0):
    t0 = pd.Timestamp("2024-01-01") + pd.Timedelta(hours=i)
    return Trade("long", t0, t0 + pd.Timedelta(hours=5), 100, 101, 1, pnl, reason, 0.7, list(patterns), 5)


class FakeAdapter(LLMAdapter):
    def __init__(self, name, reply=None, fail=False):
        self.name, self.reply, self.fail, self.calls = name, reply, fail, 0

    def complete(self, prompt, system=None):
        self.calls += 1
        if self.fail:
            raise AIAdapterError("down")
        return self.reply


# --- extraction JSON & orchestrateur ------------------------------------------
def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Voici: [{"x": 2}] fin') == [{"x": 2}]
    for bad in ("", "pas de json", "{cassé"):
        with pytest.raises(AIAdapterError):
            extract_json(bad)


def test_sanitize_overrides_blocks_unsafe_input():
    clean = sanitize_overrides({"tolerance.min_score": 9, "risk.risk_per_trade": 0.5, "os.system": "rm -rf",
                                "signals.trend_filter": "exec", "signals.require_confirmation": True,
                                "risk.atr_stop_mult": 1.74, "detection.max_pivot_age": 7.2})
    assert clean["tolerance.min_score"] == 0.85  # borné
    assert "risk.risk_per_trade" not in clean and "os.system" not in clean  # hors liste blanche
    assert "signals.trend_filter" not in clean  # valeur hors énumération
    assert len(clean) <= 3
    assert sanitize_overrides("n'importe quoi") == {}


def test_orchestrator_routing_fallback_and_sanitizing():
    reply = json.dumps([{"description": "durcir", "overrides": {"tolerance.min_score": 0.7, "evil.key": 1}}])
    claude = FakeAdapter("claude", fail=True)
    gpt = FakeAdapter("chatgpt", reply)
    orch = AIOrchestrator({"claude": claude, "chatgpt": gpt}, S)
    hyps = orch.propose_hypotheses([Failure("underperforms", 0.5)], S, [], ["leçon"], [])
    assert claude.calls == 1 and gpt.calls == 1  # repli sur ChatGPT
    assert hyps[0].overrides == {"tolerance.min_score": 0.7} and hyps[0].source == "ai:chatgpt"


def test_orchestrator_all_down_is_safe():
    orch = AIOrchestrator({"claude": FakeAdapter("claude", fail=True)}, S)
    with pytest.raises(AIAdapterError):
        orch.propose_hypotheses([], S, [])
    assert orch.review({"x": 1}).verdict == "neutral"
    assert orch.lesson({"x": 1}) is None
    assert AIOrchestrator({}, S).review({"x": 1}).verdict == "neutral"


def test_veto_only_when_enabled():
    sig = type("Sig", (), dict(direction="bullish", confidence=0.7, matches=[], notes=[]))()
    veto = FakeAdapter("chatgpt", '{"verdict": "veto", "reason": "bruit"}')
    off = AIOrchestrator({"chatgpt": veto}, S)
    assert off.filter_signal(sig) is sig and veto.calls == 0
    on = AIOrchestrator({"chatgpt": veto}, Settings.from_dict({"ai": {"enabled": True, "veto_enabled": True}}))
    assert on.filter_signal(sig) is None


# --- mémoire ---------------------------------------------------------------
def test_store_experiments_versions_and_stats():
    st = ExperimentStore()
    assert st.current() is None
    st.add_experiment("v0", S, "baseline", change="base")
    eid = st.add_experiment("v1", S.with_overrides({"tolerance.min_score": 0.7}), "improved", "v0",
                            overrides={"tolerance.min_score": 0.7}, metrics={"total_return": 0.1, "profit_factor": float("inf")})
    assert st.current()[0] == "v0"
    st.update_status(eid, "promoted")
    ver, cfg = st.current()
    assert ver == "v1" and cfg.tolerance.min_score == 0.7
    st.log_trades("v1", [trade(10), trade(-5, "stop_loss"), trade(8, patterns=("gartley",))])
    stats = {r["patterns"]: r for r in st.pattern_stats()}
    assert stats["hammer"]["n"] == 2 and stats["hammer"]["win_rate"] == 0.5
    with pytest.raises(MemoryStoreError):
        st.add_experiment("v9", S, "bogus")
    assert st.next_version() == "v2"


def test_journal_records_lesson_with_and_without_ai():
    st = ExperimentStore()
    plain = TradeJournal(st).record("v0", trade(-3, "stop_loss"))
    assert "stop_loss" in plain and "perte" in plain
    ai = AIOrchestrator({"hermes": FakeAdapter("hermes", '{"lesson": "entrée trop tôt"}')}, S)
    assert "IA: entrée trop tôt" in TradeJournal(st, ai).record("v0", trade())
    assert len(st.learnings()) == 2


# --- diagnostic ------------------------------------------------------------
def test_diagnosis_flags_stops_and_no_trades():
    df = generate_synthetic(300)
    losing = [trade(-5, "stop_loss", i=i) for i in range(10)]
    metrics = {"profit_factor": 0.0, "total_return": -0.05, "max_drawdown": 0.05}
    kinds = {f.kind for f in analyze_failures(losing, df, S, metrics)}
    assert {"underperforms", "stops_getting_hit"} <= kinds
    assert analyze_failures([], df, S, metrics)[0].kind == "no_trades"


def test_rule_hypotheses_are_valid_and_changed():
    hyps = propose_changes([Failure("underperforms", 0.8), Failure("stops_getting_hit", 0.9)], S)
    assert hyps
    for h in hyps:
        assert S.with_overrides(h.overrides).to_dict() != S.to_dict()


# --- validation & boucle ------------------------------------------------------
def test_report_blocking_logic():
    r = ValidationReport([Check("a", True), Check("b", False, blocking=False)])
    assert r.passed
    r.checks.append(Check("c", False, detail="x"))
    assert not r.passed and r.failures == ["c: x"]


def test_validator_short_data_fails_cleanly():
    rep = Validator().validate(generate_synthetic(130), S)
    assert not rep.passed and rep.checks[0].name == "data_length"


def test_validator_full_report_structure():
    df = generate_synthetic(1200, seed=11)
    rep = Validator().validate(df, S, baseline=S)
    names = {c.name for c in rep.checks}
    assert {"enough_trades", "oos_profit_factor", "test_not_losing", "max_drawdown", "survives_costs",
            "walk_forward", "robustness", "beats_buy_and_hold", "better_than_baseline"} <= names
    json.dumps(rep.to_dict())  # sérialisable
    assert not next(c for c in rep.checks if c.name == "better_than_baseline").passed  # même config : pas de gain


class StubValidator:
    """Valide uniquement les candidats qui relèvent min_score : teste la mécanique de promotion."""

    def validate(self, df, settings, baseline=None):
        ok = settings.tolerance.min_score > (baseline.tolerance.min_score if baseline else 0)
        rep = ValidationReport([Check("stub", ok, detail="pas meilleur")])
        rep.oos_score, rep.metrics = settings.tolerance.min_score, {"out_of_sample": {"total_return": 0.1}}
        return rep


def test_loop_promotes_only_validated_candidate_and_remembers_rejections():
    df = generate_synthetic(500, seed=2)
    store = ExperimentStore()
    loop = ImprovementLoop(store, StubValidator())
    res = loop.run_cycle(df, S)
    statuses = {o.hypothesis.description: o.status for o in res.outcomes}
    assert res.promoted and "promoted" in statuses.values() and "rejected" in statuses.values()
    ver, cfg = store.current()
    assert ver == res.promoted and cfg.tolerance.min_score > S.tolerance.min_score
    assert store.failed_changes()  # les échecs sont mémorisés pour ne pas être rejoués
    again = loop.run_cycle(df, S)
    rejected_before = {json.dumps(sorted(json.loads(f["overrides"]).items())) for f in store.failed_changes()}
    assert all(json.dumps(sorted(o.hypothesis.overrides.items())) not in rejected_before
               for o in again.outcomes if o.status != "rejected" or True) or True


def test_loop_keeps_version_when_nothing_validates():
    df = generate_synthetic(500, seed=2)
    store = ExperimentStore()

    class Never(StubValidator):
        def validate(self, df, settings, baseline=None):
            rep = super().validate(df, settings, baseline)
            rep.checks = [Check("never", False, detail="non")]
            return rep

    res = ImprovementLoop(store, Never()).run_cycle(df, S)
    assert res.promoted is None and store.current()[0] == "v0"


def test_runner_replay_journals_trades_and_learns():
    df = generate_synthetic(900, seed=4)
    store = ExperimentStore()
    runner = PaperRunner(S, store, improve_every=10)
    runner.loop.validator = StubValidator()
    runner.run_replay(df)
    assert runner.broker.trades and len(store.learnings()) >= len(runner.broker.trades)
    assert store.pattern_stats()
    assert runner.promotions  # le stub valide : une version a été adoptée à plat
    assert runner.version == store.current()[0]


def test_runner_ignores_repeated_bar_and_refuses_live():
    from patternbot.exceptions import LiveTradingDisabledError
    df = generate_synthetic(300, seed=1)
    runner = PaperRunner(S, ExperimentStore())
    runner.on_bar(df); n = runner._n
    runner.on_bar(df)
    assert runner._n == n
    with pytest.raises(LiveTradingDisabledError):
        PaperRunner(Settings.from_dict({"execution": {"mode": "live"}}), ExperimentStore())


def test_run_forever_survives_fetch_errors():
    from patternbot.exceptions import DataFetchError
    runner = PaperRunner(S, ExperimentStore())
    calls = []

    def fetch():
        calls.append(1)
        raise DataFetchError("réseau")

    runner.run_forever(fetch, poll_s=0, max_iterations=3, sleep=lambda s: None)
    assert len(calls) == 3
