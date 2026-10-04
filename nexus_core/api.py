"""Client Python fin : chaque methode appelle une fonction SQL et renvoie un Result.

Les refus metier (budget, hash perime, opposition...) sont des valeurs, pas des
exceptions : `Result.ok` est faux et `Result.code` dit pourquoi. Les erreurs
d'autorisation levent `psycopg.errors.RaiseException` ("forbidden") ou
`InsufficientPrivilege`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple, Optional

import psycopg
from psycopg.types.json import Jsonb


class Refused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Result:
    ok: bool
    code: str
    id: Optional[int]

    def require(self) -> int:
        if not self.ok:
            raise Refused(self.code)
        return self.id  # type: ignore[return-value]


class Claimed(NamedTuple):
    message_id: int
    recipient: str
    subject: str
    body: str
    content_hash: str


class Client:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    @classmethod
    def connect(cls, **conninfo: Any) -> "Client":
        return cls(psycopg.connect(autocommit=True, **conninfo))

    def close(self) -> None:
        self.conn.close()

    def _result(self, sql: str, *args: Any) -> Result:
        # SELECT * FROM f(...) execute f une seule fois ; SELECT (f(...)).* l'executerait
        # une fois par colonne, ce qui est inacceptable pour une fonction qui modifie l'etat.
        row = self.conn.execute(f"SELECT * FROM nexus.{sql}", args).fetchone()
        return Result(row[0], row[1], row[2])

    # budget
    def reserve(self, idem, category, cents, desc="") -> Result:
        return self._result("reserve_budget(%s,%s,%s,%s)", idem, category, cents, desc)

    def settle(self, reservation_id, actual_cents) -> Result:
        return self._result("settle_budget(%s,%s)", reservation_id, actual_cents)

    def release(self, reservation_id) -> Result:
        return self._result("release_budget(%s)", reservation_id)

    def budget_status(self) -> dict:
        return self.conn.execute("SELECT nexus.budget_status()").fetchone()[0]

    # messages
    def create_message(self, idem, channel, recipient, subject, body, max_cost_cents, purpose) -> Result:
        return self._result("create_message(%s,%s,%s,%s,%s,%s,%s)",
                            idem, channel, recipient, subject, body, max_cost_cents, purpose)

    def create_revision(self, prev_id, idem, subject, body, max_cost_cents, purpose) -> Result:
        return self._result("create_revision(%s,%s,%s,%s,%s,%s)",
                            prev_id, idem, subject, body, max_cost_cents, purpose)

    def review(self, message_id, verdict, dimensions: dict, reasons=None) -> Result:
        return self._result("submit_review(%s,%s,%s,%s)", message_id, verdict, Jsonb(dimensions), reasons)

    def approve(self, message_id, content_hash, valid_hours=24) -> Result:
        return self._result("approve(%s,%s,%s)", message_id, content_hash, valid_hours)

    def founder_reject(self, message_id, reason) -> Result:
        return self._result("founder_reject(%s,%s)", message_id, reason)

    def suppress(self, recipient, reason="opposition") -> Result:
        return self._result("add_suppression(%s,%s)", recipient, reason)

    # transport
    def claim(self, lease_seconds=300) -> Optional[Claimed]:
        row = self.conn.execute("SELECT * FROM nexus.claim_outbox(%s)", (lease_seconds,)).fetchone()
        return Claimed(*row) if row else None

    def precheck(self, message_id) -> Result:
        return self._result("precheck_before_send(%s)", message_id)

    def mark_sent(self, message_id, provider_ref, actual_cost_cents=0) -> Result:
        return self._result("mark_sent(%s,%s,%s)", message_id, provider_ref, actual_cost_cents)

    def mark_failed(self, message_id, error, actual_cost_cents=0, retryable=False) -> Result:
        return self._result("mark_failed(%s,%s,%s,%s)", message_id, error, actual_cost_cents, retryable)

    def notify_founder(self, kind, ref, text) -> Result:
        return self._result("notify_founder(%s,%s,%s)", kind, ref, text)

    def notifications(self) -> list:
        return self.conn.execute("SELECT nexus.get_notifications()").fetchone()[0]

    def stuck_alerts(self, age_minutes) -> int:
        return self.conn.execute("SELECT nexus.raise_stuck_alerts(%s)", (age_minutes,)).fetchone()[0]

    def verify_audit(self) -> Optional[int]:
        return self.conn.execute("SELECT nexus.verify_audit_chain()").fetchone()[0]

    def get_message(self, message_id) -> Optional[dict]:
        """Texte exact et hash : c'est ce que l'UI montre avant approve()."""
        return self.conn.execute("SELECT nexus.get_message(%s)", (message_id,)).fetchone()[0]

    def content_hash(self, message_id) -> str:
        return self.get_message(message_id)["content_hash"]
