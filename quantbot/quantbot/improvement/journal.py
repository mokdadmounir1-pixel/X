"""Journal de trading : chaque trade clôturé produit une leçon mémorisée.

La leçon est factuelle (règles) et enrichie par une IA si disponible ; elle
alimente ensuite les prompts de la boucle d'amélioration.
"""
from __future__ import annotations

from typing import Optional

from ..execution.broker import Trade
from ..logging_utils import get_logger
from ..memory.store import ExperimentStore

log = get_logger("journal")


class TradeJournal:
    def __init__(self, store: ExperimentStore, orchestrator=None) -> None:
        self.store = store
        self.orchestrator = orchestrator

    def record(self, version: str, trade: Trade) -> str:
        outcome = "gain" if trade.pnl > 0 else "perte"
        lesson = (f"{trade.side} {','.join(trade.patterns) or '?'} conf={trade.confidence:.2f} -> "
                  f"{trade.reason}, {outcome} {trade.pnl:.2f} en {trade.bars_held} barres")
        if self.orchestrator is not None:
            ai: Optional[str] = self.orchestrator.lesson({
                "side": trade.side, "patterns": trade.patterns, "confidence": round(trade.confidence, 3),
                "exit_reason": trade.reason, "pnl": round(trade.pnl, 2), "bars_held": trade.bars_held})
            if ai:
                lesson += f" | IA: {ai}"
        self.store.log_trades(version, [trade])
        self.store.add_learning(version, lesson)
        log.info("Journal: %s", lesson)
        return lesson
