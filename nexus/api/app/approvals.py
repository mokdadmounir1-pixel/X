from __future__ import annotations
from . import audit
from .canon import params_hash
from .db import J
from .errors import Conflict, EmergencyStopped, Forbidden, NotFound, Invalid


def request(conn, task: dict, requested_by: str, ttl_min: int | None, settings=None) -> dict:
    default = getattr(settings, "approval_default_ttl_min", 24 * 60)
    cap = getattr(settings, "approval_max_ttl_min", 72 * 60)
    ttl = ttl_min if ttl_min is not None else default
    if not 1 <= ttl <= cap:
        raise Invalid(f"Durée d'approbation : 1 à {cap} minutes", code="bad_ttl")
    row = conn.execute(
        """INSERT INTO approvals(task_id, action, params, params_hash, requested_by, expires_at)
           VALUES (%s,%s,%s,%s,%s, now() + make_interval(mins => %s)) RETURNING *""",
        (task["id"], task["kind"], J(task["params"]), task["params_hash"], requested_by, ttl)).fetchone()
    audit.record(conn, requested_by, "approval.requested", "approval", row["id"], task["correlation_id"],
                 details={"task_id": str(task["id"]), "action": task["kind"], "params_hash": task["params_hash"],
                          "expires_at": row["expires_at"].isoformat()})
    return row


def get(conn, approval_id, lock=False) -> dict:
    row = conn.execute("SELECT * FROM approvals WHERE id=%s" + (" FOR UPDATE" if lock else ""),
                       (str(approval_id),)).fetchone()
    if not row:
        raise NotFound("Approbation introuvable")
    return row


def invalidate_for_task(conn, task_id, reason: str, actor: str) -> int:
    rows = conn.execute(
        """UPDATE approvals SET status='invalidated', decision_note=coalesce(decision_note,'') || %s
           WHERE task_id=%s AND status IN ('pending','approved') RETURNING id""",
        (f"[{reason}]", str(task_id))).fetchall()
    for r in rows:
        audit.record(conn, actor, "approval.invalidated", "approval", r["id"], details={"reason": reason})
    return len(rows)


def decide(conn, approval_id, principal, decision: str, note: str = "") -> dict:
    from . import tasks
    principal.require("fondateur")
    if decision not in ("approve", "reject"):
        raise Invalid("decision : approve ou reject")
    if tasks.emergency_active(conn, lock=True):
        raise EmergencyStopped("Arrêt d'urgence actif : aucune décision d'approbation")
    ap = get(conn, approval_id, lock=True)
    task = tasks.get(conn, ap["task_id"], lock=True)
    if ap["status"] != "pending":
        raise Conflict(f"Approbation déjà {ap['status']}", code="not_pending")
    expired = conn.execute("SELECT %s <= now() AS e", (ap["expires_at"],)).fetchone()["e"]
    if expired:
        conn.execute("UPDATE approvals SET status='expired' WHERE id=%s", (ap["id"],))
        audit.record(conn, principal.username, "approval.expired", "approval", ap["id"], task["correlation_id"], "denied")
        raise Conflict("Approbation expirée", code="approval_expired")
    if ap["params_hash"] != task["params_hash"]:
        conn.execute("UPDATE approvals SET status='invalidated' WHERE id=%s", (ap["id"],))
        audit.record(conn, principal.username, "approval.invalidated", "approval", ap["id"], task["correlation_id"],
                     "denied", {"reason": "params_changed"})
        raise Conflict("Les paramètres ont changé depuis la demande", code="approval_params_changed")
    new = "approved" if decision == "approve" else "rejected"
    conn.execute("UPDATE approvals SET status=%s, decided_by=%s, decided_at=now(), decision_note=%s WHERE id=%s",
                 (new, principal.username, note[:500], ap["id"]))
    audit.record(conn, principal.username, f"approval.{new}", "approval", ap["id"], task["correlation_id"],
                 details={"task_id": str(task["id"]), "params_hash": ap["params_hash"]})
    if new == "approved":
        tasks.set_status(conn, task, "queued", principal.username)
    else:
        tasks.set_status(conn, task, "cancelled", principal.username, error_code="approval_rejected")
    return get(conn, ap["id"])


def consume_for_execution(conn, task: dict) -> None:
    """Appelée au démarrage d'une tâche de niveau 2. Lève Forbidden si l'approbation n'est pas valable
    MAINTENANT : approuvée, non expirée, non consommée, empreinte identique aux paramètres actuels."""
    ap = conn.execute(
        """SELECT * FROM approvals WHERE task_id=%s AND status='approved' ORDER BY decided_at DESC LIMIT 1 FOR UPDATE""",
        (task["id"],)).fetchone()
    if not ap:
        raise Forbidden("Aucune approbation valable", code="approval_missing")
    if conn.execute("SELECT %s <= now() AS e", (ap["expires_at"],)).fetchone()["e"]:
        conn.execute("UPDATE approvals SET status='expired' WHERE id=%s", (ap["id"],))
        raise Forbidden("Approbation expirée", code="approval_expired")
    current = params_hash(task["kind"], task["params"])
    if not (ap["params_hash"] == current == task["params_hash"]):
        conn.execute("UPDATE approvals SET status='invalidated' WHERE id=%s", (ap["id"],))
        raise Forbidden("Paramètres modifiés depuis l'approbation", code="approval_params_changed")
    conn.execute("UPDATE approvals SET status='consumed', consumed_at=now() WHERE id=%s", (ap["id"],))
    audit.record(conn, "system", "approval.consumed", "approval", ap["id"], task["correlation_id"])
