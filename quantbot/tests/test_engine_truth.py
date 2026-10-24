"""Le cœur de vérité : parité, trous de données, edge planté retrouvé, absence de faux PASS sur du hasard."""
import numpy as np
import pandas as pd
import pytest

from quantbot.backtest.engine import Backtester
from quantbot.config import Settings
from quantbot.core.sim import TradingEngine
from quantbot.data.loaders import generate_synthetic
from quantbot.lab.gates import GateCfg
from quantbot.lab.locked import split_locked
from quantbot.lab.pipeline import evaluate_locked, evaluate_research, spec_hash
from quantbot.lab.registry import TrialRegistry
from tests.helpers import OracleSignals, planted_frame

S = Settings()


def _sig(trades):
    return [(str(t.entry_time), str(t.exit_time), t.side, round(t.entry, 9), round(t.exit, 9), round(t.pnl, 9), t.reason)
            for t in trades]


def test_backtest_and_incremental_feed_are_identical():
    """Le backtest n'est qu'un rejeu : alimenter le moteur barre après barre donne exactement les mêmes trades."""
    df = generate_synthetic(700, seed=3)
    batch = Backtester(S).run(df)
    eng = TradingEngine(S)
    for t in range(S.backtest.warmup_bars, len(df)):
        eng.on_bar(df.iloc[: t + 1])
        eng.on_bar(df.iloc[: t + 1])  # une barre déjà vue est ignorée (flux live qui répète)
    eng.finish(df)
    assert _sig(batch.trades) == _sig(eng.broker.trades)
    assert batch.metrics["n_trades"] > 0


def test_r_multiple_matches_pnl_over_planned_risk():
    df = planted_frame(1200, seed=1)
    res = Backtester(S, signal_engine=OracleSignals()).run(df)
    assert res.trades and all(t.risk_amount > 0 for t in res.trades)
    stop_losses = [t for t in res.trades if t.reason == "stop_loss"]
    assert stop_losses and all(-1.6 < t.r < -0.9 for t in stop_losses)  # ~ -1R, un peu plus avec coûts/slippage
    assert max(t.r for t in res.trades) > 1.0


def test_data_hole_closes_position_and_blocks_cross_gap_trades():
    df = planted_frame(900, seed=2)
    hole = df.copy()
    shift = pd.Timedelta(days=60)
    hole.index = list(df.index[:500]) + [t + shift for t in df.index[500:]]
    hole.iloc[500:, :4] = hole.iloc[500:, :4].to_numpy() * 1.05  # saut de prix caché par le trou
    eng = TradingEngine(S, signal_engine=OracleSignals())
    eng.run_replay(hole)
    eng.finish(hole)
    assert len(eng.holes) == 1 and eng.holes[0][2] > 1000
    for t in eng.broker.trades:  # aucun trade ne traverse le trou
        assert not (t.entry_time < hole.index[500] <= t.exit_time and t.reason != "data_gap")
    # pas de signal pendant le ré-échauffement qui suit le trou
    late = [t for t in eng.broker.trades if t.entry_time >= hole.index[500]]
    assert all(t.entry_time >= hole.index[500 + S.backtest.warmup_bars - 1] for t in late)


def test_planted_edge_is_recovered_by_the_whole_chain():
    df = planted_frame(5000, seed=11, edge=True)
    research, locked = split_locked(df)
    reg = TrialRegistry()
    ev = evaluate_research(research, S, reg, GateCfg(), OracleSignals())
    assert ev.metrics["n_trades"] >= 60 and ev.metrics["expectancy_R"] > 0.3
    failed = [g.name for g in ev.gates if not g.ok]
    assert ev.verdict == "PASS", (ev.verdict, ev.reason, failed)
    final = evaluate_locked(locked, S, reg, GateCfg(), OracleSignals(), min_trades=15)  # fenêtre courte en test
    assert final["verdict"] == "CONFIRMED" and reg.locked_reads(spec_hash(S)) == 1


@pytest.mark.slow
def test_false_pass_rate_on_markets_without_edge_stays_low():
    """Garde-fou de calibration (pytest -m slow) : sur des marchés où le signal ne prédit RIEN, quasi aucun PASS.
    Mesure de référence (scripts/calibrate_gates.py, 120 séries x 5000 barres) : 1 faux PASS, borne haute 95 % = 3,9 %.
    Ici 12 séries : au plus 1 PASS toléré (une série sur 12 reste statistiquement plausible)."""
    verdicts = []
    for seed in range(12):
        df = planted_frame(5000, seed=900 + seed, edge=False)
        research, _ = split_locked(df)
        verdicts.append(evaluate_research(research, S, TrialRegistry(), GateCfg(), OracleSignals()).verdict)
    assert verdicts.count("PASS") <= 1, verdicts


def test_too_few_trades_is_never_a_pass_even_with_a_real_edge():
    df = planted_frame(900, seed=11, edge=True)  # peu de trades : l'échantillon ne permet pas de conclure
    research, _ = split_locked(df)
    ev = evaluate_research(research, S, TrialRegistry(), GateCfg(), OracleSignals())
    assert ev.verdict != "PASS" and not next(g for g in ev.gates if g.name == "n_trades").ok


def test_more_trials_make_the_same_result_harder_to_pass():
    df = planted_frame(5000, seed=11, edge=True)
    research, _ = split_locked(df)
    lone = evaluate_research(research, S, TrialRegistry(), GateCfg(), OracleSignals())
    crowded = TrialRegistry()
    for i in range(300):  # 300 autres essais perdus dans l'historique
        crowded.record_trial(f"other{i}", "d", float(np.random.default_rng(i).normal(0, 0.15)), 80)
    after = evaluate_research(research, S, crowded, GateCfg(), OracleSignals())
    dsr = lambda ev: next(g.value for g in ev.gates if g.name == "deflated_sharpe")
    assert after.n_trials > lone.n_trials and dsr(after) <= dsr(lone)


def test_spec_hash_changes_with_strategy_and_thresholds_but_not_with_logging():
    base = spec_hash(S)
    assert spec_hash(S.with_overrides({"risk.reward_risk": 3.0})) != base
    assert spec_hash(S, GateCfg(min_expectancy=0.05)) != base  # assouplir un seuil change l'identité
    assert spec_hash(S.with_overrides({"logging.level": "DEBUG"})) == base
