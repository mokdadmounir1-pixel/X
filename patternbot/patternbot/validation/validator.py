"""Validation « sans se mentir » : OOS, test final, coûts, walk-forward, robustesse.

Une version de stratégie n'est promue que si TOUS les contrôles bloquants passent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from ..backtest.engine import Backtester, BacktestResult
from ..config import Settings
from ..exceptions import ConfigError, PatternBotError
from ..logging_utils import get_logger

log = get_logger("validation")

# Paramètres secoués pour le test de robustesse (valeurs numériques uniquement)
JITTER_KEYS = ["tolerance.min_score", "tolerance.tolerance_percentage", "signals.min_confidence",
               "risk.atr_stop_mult", "risk.reward_risk"]


@dataclass
class Check:
    name: str
    passed: bool
    value: object = None
    detail: str = ""
    blocking: bool = True


@dataclass
class ValidationReport:
    checks: list[Check] = field(default_factory=list)
    oos_score: float = float("-inf")
    metrics: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.blocking)

    @property
    def failures(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if c.blocking and not c.passed]

    def to_dict(self) -> dict:
        return {"passed": self.passed, "oos_score": self.oos_score, "metrics": self.metrics,
                "checks": [{"name": c.name, "passed": c.passed, "value": _jsonable(c.value),
                            "detail": c.detail, "blocking": c.blocking} for c in self.checks]}


def _jsonable(v):
    if isinstance(v, float) and not np.isfinite(v):
        return str(v)
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    return v


def oos_score(metrics: dict) -> float:
    """Score risque-ajusté simple : rendement - 0.5 * drawdown."""
    return float(metrics["total_return"] - 0.5 * metrics["max_drawdown"])


class Validator:
    def __init__(self) -> None:
        pass

    # --- utilitaires -----------------------------------------------------
    @staticmethod
    def split_bounds(n: int, split: tuple) -> list[tuple[int, int]]:
        a = int(n * split[0])
        b = a + int(n * split[1])
        return [(0, a), (a, b), (b, n)]

    def _run(self, df: pd.DataFrame, settings: Settings, start: int, end: int,
             cost_mult: float = 1.0) -> Optional[BacktestResult]:
        """Backtest sur [start,end) avec `warmup` barres de contexte préalables."""
        warm = settings.backtest.warmup_bars
        lo = max(0, start - warm)
        segment = df.iloc[lo:end]
        if len(segment) < warm + 20:
            return None
        return Backtester(settings, cost_mult).run(segment)

    # --- validation complète --------------------------------------------
    def validate(self, df: pd.DataFrame, settings: Settings,
                 baseline: Optional[Settings] = None) -> ValidationReport:
        v = settings.validation
        report = ValidationReport()
        n = len(df)
        (i0, i1), (o0, o1), (t0, t1) = self.split_bounds(n, v.split)

        full = self._run(df, settings, 0, n)
        ins = self._run(df, settings, i0, i1)
        oos = self._run(df, settings, o0, o1)
        test = self._run(df, settings, t0, t1)
        if None in (full, ins, oos, test):
            report.checks.append(Check("data_length", False, n, "données trop courtes pour le split 60/20/20"))
            return report
        report.metrics = {"in_sample": ins.metrics, "out_of_sample": oos.metrics, "test": test.metrics,
                          "full": full.metrics}
        report.oos_score = oos_score(oos.metrics)

        oos_trades = oos.metrics["n_trades"] + test.metrics["n_trades"]
        report.checks.append(Check("enough_trades", oos_trades >= v.min_trades, oos_trades,
                                   f"{oos_trades} trades hors échantillon < {v.min_trades}"))
        report.checks.append(Check("oos_profit_factor", oos.metrics["profit_factor"] >= v.min_profit_factor,
                                   oos.metrics["profit_factor"], f"PF OOS < {v.min_profit_factor}"))
        report.checks.append(Check("test_not_losing", test.metrics["total_return"] > 0,
                                   test.metrics["total_return"], "test final perdant"))
        report.checks.append(Check("max_drawdown", full.metrics["max_drawdown"] <= v.max_drawdown,
                                   full.metrics["max_drawdown"], f"drawdown > {v.max_drawdown:.0%}"))

        stressed = self._run(df, settings, 0, n, cost_mult=v.cost_stress_multiplier)
        sr = stressed.metrics["total_return"] if stressed else float("nan")
        report.checks.append(Check("survives_costs", bool(stressed) and sr > 0, sr,
                                   f"rendement <= 0 avec coûts x{v.cost_stress_multiplier}"))

        report.checks.append(self._walk_forward(df, settings))
        report.checks.append(self._robustness(df, settings, o0, t1))

        bh = float(df["close"].iloc[o1 - 1] / df["close"].iloc[o0] - 1.0)
        report.checks.append(Check("beats_buy_and_hold", oos.metrics["total_return"] > bh,
                                   {"strategy": oos.metrics["total_return"], "buy_hold": bh},
                                   "ne bat pas le buy & hold (informatif)", blocking=False))

        if baseline is not None:
            base = self._run(df, baseline, o0, o1)
            base_score = oos_score(base.metrics) if base else float("-inf")
            gain = report.oos_score - base_score
            report.checks.append(Check("better_than_baseline", gain > v.min_improvement, gain,
                                       f"gain OOS {gain:.4f} <= {v.min_improvement}"))
        return report

    def _walk_forward(self, df: pd.DataFrame, settings: Settings) -> Check:
        v = settings.validation
        warm = settings.backtest.warmup_bars
        n = len(df)
        k = v.walk_forward_windows
        usable = n - warm
        if usable < k * 40:
            return Check("walk_forward", False, None, "données insuffisantes")
        edges = [warm + round(usable * j / k) for j in range(k + 1)]
        returns = []
        for a, b in zip(edges[:-1], edges[1:]):
            res = self._run(df, settings, a, b)
            returns.append(res.metrics["total_return"] if res else 0.0)
        ratio = float(np.mean([r > 0 for r in returns]))
        return Check("walk_forward", ratio >= v.min_wf_positive_ratio, ratio,
                     f"{ratio:.0%} de fenêtres positives < {v.min_wf_positive_ratio:.0%}")

    def _robustness(self, df: pd.DataFrame, settings: Settings, start: int, end: int) -> Check:
        v = settings.validation
        base = settings.to_dict()
        wins = total = 0
        for key in JITTER_KEYS:
            section, name = key.split(".")
            value = base[section][name]
            for factor in (1 - v.robustness_jitter, 1 + v.robustness_jitter):
                try:
                    neighbor = settings.with_overrides({key: round(value * factor, 6)})
                except ConfigError:
                    continue  # voisin invalide : ignoré
                try:
                    res = self._run(df, neighbor, start, end)
                except PatternBotError as exc:
                    log.warning("Voisin %s x%.2f en échec : %s", key, factor, exc)
                    continue
                if res is None:
                    continue
                total += 1
                wins += res.metrics["total_return"] > 0
        if total == 0:
            return Check("robustness", False, None, "aucun voisin évaluable")
        ratio = wins / total
        return Check("robustness", ratio >= v.min_robust_ratio, ratio,
                     f"{ratio:.0%} de voisins rentables < {v.min_robust_ratio:.0%}")
