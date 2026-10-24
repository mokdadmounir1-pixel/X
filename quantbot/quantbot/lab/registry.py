"""Registre d'essais append-only, chaîné par hachage.

Compte TOUS les essais (y compris les perdants) : c'est ce nombre qui alimente le DSR.
Chaque ligne contient le hachage de la précédente : toute altération est détectable.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ..exceptions import MemoryStoreError

GENESIS = "0" * 64


def canonical_hash(obj: Any) -> str:
    """SHA-256 d'un objet JSON sérialisé de façon canonique (clés triées)."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class TrialRegistry:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self.path = Path(path) if path else None
        self._events: list[dict] = []
        if self.path and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._events.append(json.loads(line))
            if not self.verify():
                raise MemoryStoreError(f"Registre altéré : {self.path}")

    @staticmethod
    def _digest(prev: str, body: dict) -> str:
        return hashlib.sha256((prev + json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)).encode()).hexdigest()

    def append(self, kind: str, payload: dict) -> dict:
        prev = self._events[-1]["hash"] if self._events else GENESIS
        body = {"seq": len(self._events), "ts": time.time(), "kind": kind, "payload": payload}
        event = {**body, "prev": prev, "hash": self._digest(prev, body)}
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, default=str) + "\n")
        self._events.append(event)
        return event

    def verify(self) -> bool:
        prev = GENESIS
        for i, e in enumerate(self._events):
            body = {k: e[k] for k in ("seq", "ts", "kind", "payload")}
            if e["seq"] != i or e["prev"] != prev or e["hash"] != self._digest(prev, body):
                return False
            prev = e["hash"]
        return True

    # --- requêtes --------------------------------------------------------
    def events(self, kind: Optional[str] = None) -> list[dict]:
        return [e for e in self._events if kind is None or e["kind"] == kind]

    def record_trial(self, spec_hash: str, data_hash: str, sharpe: float, n_trades: int, **extra: Any) -> bool:
        """Enregistre un essai ; une ré-exécution identique (même spec + mêmes données) ne compte qu'une fois."""
        for e in self.events("trial"):
            if e["payload"]["spec_hash"] == spec_hash and e["payload"]["data_hash"] == data_hash:
                return False
        self.append("trial", {"spec_hash": spec_hash, "data_hash": data_hash, "sharpe": float(sharpe),
                              "n_trades": int(n_trades), **extra})
        return True

    def n_trials(self) -> int:
        """Essais distincts + lectures de la période verrouillée (chacune est un essai de plus)."""
        return len(self.events("trial")) + len(self.events("locked_read"))

    def var_sharpe(self) -> float:
        srs = [e["payload"]["sharpe"] for e in self.events("trial")]
        return float(np.var(srs)) if len(srs) > 1 else 0.0

    def locked_reads(self, spec_hash: Optional[str] = None) -> int:
        return sum(1 for e in self.events("locked_read") if spec_hash is None or e["payload"]["spec_hash"] == spec_hash)
