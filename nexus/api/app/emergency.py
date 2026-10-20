from __future__ import annotations
from . import audit, approvals
from .db import J
from .errors import Forbidden


def status(conn) -> dict:
    return conn.execute("SELECT * FROM system_state WHERE id=1").fetchone()


def engage(conn, principal, reason: str) -> dict:
    principal.require("operateur")
    st = conn.execute("SELECT * FROM system_state WHERE id=1 FOR UPDATE").fetchone()
    if st["emergency_stop"]:
        return st
    cancelled = conn.execute(
        """UPDATE tasks SET status='cancelled', error_code='emergency_stop', finished_at=now()
           WHERE status IN ('draft','queued','awaiting_approval') RETURNING id, kind""").fetchall()
    for c in cancelled:
        approvals.invalidate_for_task(conn, c["id"], "emergency_stop", principal.username)
    running = conn.execute(
        "UPDATE tasks SET cancel_requested=true WHERE status='running' RETURNING id, kind").fetchall()
    external = conn.execute(
        "SELECT id, kind, target, performed_at FROM external_actions ORDER BY performed_at DESC LIMIT 50").fetchall()
    report = {
        "cancelled": [{"id": str(c["id"]), "kind": c["kind"]} for c in cancelled],
        "still_running": [{"id": str(r["id"]), "kind": r["kind"],
                           "note": "arrêt demandé ; la tâche s'arrête à son prochain point de contrôle"} for r in running],
        "external_actions_already_done": [{"id": str(e["id"]), "kind": e["kind"], "target": e["target"],
                                           "at": e["performed_at"].isoformat()} for e in external],
    }
    conn.execute("""UPDATE system_state SET emergency_stop=true, stopped_at=now(), stopped_by=%s, reason=%s, report=%s
                    WHERE id=1""", (principal.username, reason[:300], J(report)))
    audit.record(conn, principal.username, "emergency.engaged", "system", "1", outcome="ok",
                 details={"reason": reason[:300], "cancelled": len(cancelled), "still_running": len(running),
                          "external_done": len(external)})
    return status(conn)


def rearm(conn, principal, confirm: str) -> dict:
    principal.require("fondateur")
    if confirm != "REARMER":
        raise Forbidden("Confirmation explicite requise : REARMER", code="confirmation_required")
    conn.execute("""UPDATE system_state SET emergency_stop=false, rearmed_at=now(), rearmed_by=%s WHERE id=1""",
                 (principal.username,))
    audit.record(conn, principal.username, "emergency.rearmed", "system", "1")
    return status(conn)
