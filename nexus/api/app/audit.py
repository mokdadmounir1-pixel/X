from __future__ import annotations
from .db import J


def record(conn, actor: str, action: str, entity_type: str | None = None, entity_id=None,
           correlation_id=None, outcome: str = "ok", details: dict | None = None) -> None:
    """Ajoute un événement au journal. Les empreintes sont calculées par la base."""
    conn.execute(
        """INSERT INTO audit_events(actor, action, entity_type, entity_id, correlation_id, outcome, details)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (actor, action, entity_type, None if entity_id is None else str(entity_id),
         None if correlation_id is None else str(correlation_id), outcome, J(details or {})))


def verify(conn) -> dict:
    bad = conn.execute("SELECT verify_audit_chain() AS bad").fetchone()["bad"]
    n = conn.execute("SELECT count(*) AS n FROM audit_events").fetchone()["n"]
    last = conn.execute("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    return {"ok": bad is None, "first_bad_seq": bad, "events": n, "last_hash": last["hash"] if last else None}
