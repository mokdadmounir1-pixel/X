"""Boucle d'auto-amélioration contrôlée : log → analyse → idées → test → comparaison."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from ..backtest.engine import Backtester
from ..config import Settings
from ..exceptions import ConfigError, PatternBotError
from ..logging_utils import get_logger
from ..memory.store import ExperimentStore
from ..validation.validator import ValidationReport, Validator
from .diagnosis import Hypothesis, analyze_failures, propose_changes

log = get_logger("improvement")


@dataclass
class CandidateOutcome:
    hypothesis: Hypothesis
    version: str
    status: str
    reason: str
    oos_score: float = float("-inf")


@dataclass
class CycleResult:
    base_version: str
    promoted: Optional[str]
    pending_approval: Optional[str] = None
    failures: list = field(default_factory=list)
    outcomes: list[CandidateOutcome] = field(default_factory=list)


class ImprovementLoop:
    def __init__(self, store: ExperimentStore, validator: Optional[Validator] = None,
                 orchestrator=None, max_candidates: int = 4) -> None:
        self.store = store
        self.validator = validator or Validator()
        self.orchestrator = orchestrator
        self.max_candidates = max_candidates

    def ensure_baseline(self, settings: Settings) -> tuple[str, Settings]:
        cur = self.store.current()
        if cur is not None:
            return cur
        self.store.add_experiment("v0", settings, "baseline", change="Stratégie de base")
        return "v0", settings

    def run_cycle(self, df: pd.DataFrame, settings: Settings, auto_promote: bool = True) -> CycleResult:
        version, current = self.ensure_baseline(settings)
        # 1. LOG
        result = Backtester(current).run(df)
        self.store.log_trades(version, result.trades)
        # 2. ANALYSE
        failures = analyze_failures(result.trades, df, current, result.metrics, result.rejections)
        log.info("Cycle sur %s : %d défaillance(s) détectée(s)", version, len(failures))
        self.store.add_learning(version, "failures=" + ",".join(f.kind for f in failures))
        # 3. IDEES (IA si disponible, règles sinon / en complément)
        hyps = propose_changes(failures, current)
        if self.orchestrator is not None:
            try:
                hyps = self.orchestrator.propose_hypotheses(
                    failures, current, self.store.failed_changes(),
                    self.store.learnings()[-20:], self.store.pattern_stats()) + hyps
            except PatternBotError:
                log.exception("Orchestrateur indisponible, repli sur les règles")
        hyps = _dedupe(hyps, self.store.failed_changes())[: self.max_candidates]

        # 4. TEST
        out = CycleResult(version, None, failures)
        passed: list[tuple[float, int, Hypothesis, Settings, ValidationReport]] = []
        for h in hyps:
            cand_version = self.store.next_version()
            try:
                candidate = current.with_overrides(h.overrides)
                report = self.validator.validate(df, candidate, baseline=current)
            except (ConfigError, PatternBotError) as exc:
                self.store.add_experiment(cand_version, current, "rejected", version, h.description,
                                          h.overrides, reason=f"erreur: {exc}")
                out.outcomes.append(CandidateOutcome(h, cand_version, "rejected", str(exc)))
                continue
            metrics = report.metrics.get("out_of_sample", {})
            if report.passed:
                exp_id = self.store.add_experiment(cand_version, candidate, "improved", version, h.description,
                                                   h.overrides, metrics, report.to_dict())
                passed.append((report.oos_score, exp_id, h, candidate, report))
                out.outcomes.append(CandidateOutcome(h, cand_version, "improved", "validations OK", report.oos_score))
            else:
                reason = "; ".join(report.failures)
                self.store.add_experiment(cand_version, candidate, "rejected", version, h.description,
                                          h.overrides, metrics, report.to_dict(), reason)
                out.outcomes.append(CandidateOutcome(h, cand_version, "rejected", reason, report.oos_score))

        # 5. COMPARE : promotion du meilleur candidat validé, sinon on garde la version courante
        if passed:
            passed.sort(key=lambda x: -x[0])
            score, exp_id, h, candidate, _ = passed[0]
            best = next(o for o in out.outcomes if o.hypothesis is h)
            if auto_promote:
                self.store.update_status(exp_id, "promoted", "meilleur candidat validé")
                best.status = "promoted"
                out.promoted = best.version
                self.store.add_learning(best.version, f"promu: {h.description}")
                log.info("Version %s promue : %s", best.version, h.description)
            else:  # réel : un humain approuve (patternbot approve <version>)
                out.pending_approval = best.version
                self.store.add_learning(best.version, f"validée, en attente d'approbation: {h.description}")
                log.warning("Version %s validée : approbation manuelle requise", best.version)
        else:
            self.store.add_learning(version, "aucun candidat ne passe les validations : version conservée")
            log.info("Aucun candidat validé : on garde %s", version)
        return out


def _dedupe(hyps: list[Hypothesis], failed: list[dict]) -> list[Hypothesis]:
    import json
    seen = {json.dumps(sorted(json.loads(f["overrides"]).items())) for f in failed if f.get("overrides")}
    out = []
    for h in hyps:
        key = json.dumps(sorted(h.overrides.items()))
        if h.overrides and key not in seen:
            seen.add(key)
            out.append(h)
    return out
