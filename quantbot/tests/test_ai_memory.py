import json

import pandas as pd
import pytest

from quantbot.ai.adapters import LLMAdapter, extract_json
from quantbot.ai.orchestrator import AIOrchestrator
from quantbot.config import Settings
from quantbot.data.loaders import generate_synthetic
from quantbot.exceptions import AIAdapterError, MemoryStoreError
from quantbot.execution.broker import Trade
from quantbot.improvement.diagnosis import (Failure, Hypothesis, analyze_failures, propose_changes,
                                              sanitize_overrides)
from quantbot.improvement.journal import TradeJournal
from quantbot.memory.store import ExperimentStore

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
    ai = AIOrchestrator({"gemini": FakeAdapter("gemini", '{"lesson": "entrée trop tôt"}')}, S)
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


