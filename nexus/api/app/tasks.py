from __future__ import annotations
import uuid
from . import audit, approvals
from .canon import params_hash
from .db import J
from .errors import Conflict, EmergencyStopped, Invalid, NotFound
from .kinds import KINDS, validate_params

TERMINAL = {"succeeded", "failed", "cancelled"}
ALLOWED = {
    "draft": {"queued", "awaiting_approval", "cancelled"},
    "queued": {"running", "awaiting_approval", "cancelled", "failed"},
    "awaiting_approval": {"queued", "cancelled"},
    "running": {"succeeded", "failed", "cancelled", "queued"},
}


def emergency_active(conn, lock: bool = False) -> bool:
    q = "SELECT emergency_stop FROM system_state WHERE id=1" + (" FOR SHARE" if lock else "")
    return bool(conn.execute(q).fetchone()["emergency_stop"])


def get(conn, task_id, lock: bool = False) -> dict:
    row = conn.execute("SELECT * FROM tasks WHERE id=%s" + (" FOR UPDATE" if lock else ""), (str(task_id),)).fetchone()
    if not row:
        raise NotFound("Tâche introuvable")
    return row


def set_status(conn, task: dict, new: str, actor: str, **fields) -> dict:
    if new not in ALLOWED.get(task["status"], set()):
        raise Conflict(f"Transition interdite : {task['status']} → {new}", code="bad_transition")
    sets, vals = ["status=%s"], [new]
    for k, v in fields.items():
        sets.append(f"{k}=%s")
        vals.append(J(v) if isinstance(v, (dict, list)) else v)
    if new == "queued" and "queued_at" not in fields:
        sets.append("queued_at=now()")
    if new in TERMINAL:
        sets.append("finished_at=now()")
    row = conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=%s RETURNING *", (*vals, task["id"])).fetchone()
    audit.record(conn, actor, f"task.{new}", "task", task["id"], task["correlation_id"],
                 "ok" if new != "failed" else "error",
                 {"from": task["status"], "kind": task["kind"], "error_code": fields.get("error_code")})
    return row


def create(conn, *, kind: str, title: str, params: dict, created_by: str, owner: str | None = None,
           correlation_id=None, depends_on: list | None = None, input_refs: list | None = None,
           submit: bool = True, approval_ttl_min: int | None = None, max_attempts: int | None = None,
           settings=None) -> dict:
    """Crée une tâche (draft), puis la soumet : queued, ou awaiting_approval si niveau 2."""
    if emergency_active(conn, lock=True):
        raise EmergencyStopped("Arrêt d'urgence actif : aucune nouvelle tâche")
    clean = validate_params(kind, params)
    spec = KINDS[kind]
    corr = correlation_id or uuid.uuid4()
    row = conn.execute(
        """INSERT INTO tasks(kind,title,owner,auth_level,params,params_hash,correlation_id,created_by,
                             timeout_s,input_refs,max_attempts)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (kind, title[:200], owner or spec.owner, spec.level, J(clean), params_hash(kind, clean), str(corr),
         created_by, spec.timeout_s, J(input_refs or []), max_attempts if max_attempts is not None else 2)).fetchone()
    for dep in depends_on or []:
        conn.execute("INSERT INTO task_dependencies(task_id, depends_on_id) VALUES (%s,%s)", (row["id"], str(dep)))
    audit.record(conn, created_by, "task.draft", "task", row["id"], corr,
                 details={"kind": kind, "level": spec.level, "depends_on": [str(d) for d in depends_on or []]})
    if not submit:
        return row
    if spec.level >= 2:
        row = set_status(conn, row, "awaiting_approval", created_by)
        approvals.request(conn, row, created_by, approval_ttl_min, settings)
        return get(conn, row["id"])
    return set_status(conn, row, "queued", created_by)


def update_params(conn, task_id, new_params: dict, actor: str, settings=None) -> dict:
    """Toute modification invalide les approbations existantes ; une tâche de niveau 2
    repasse en attente d'approbation avec une nouvelle demande."""
    task = get(conn, task_id, lock=True)
    if task["status"] not in ("draft", "queued", "awaiting_approval"):
        raise Conflict(f"Modification impossible en état {task['status']}", code="not_editable")
    clean = validate_params(task["kind"], new_params)
    invalidated = approvals.invalidate_for_task(conn, task["id"], "params_modified", actor)
    conn.execute("UPDATE tasks SET params=%s, params_hash=%s, version=version+1 WHERE id=%s",
                 (J(clean), params_hash(task["kind"], clean), task["id"]))
    audit.record(conn, actor, "task.params_modified", "task", task["id"], task["correlation_id"],
                 details={"approvals_invalidated": invalidated})
    task = get(conn, task["id"])
    if task["auth_level"] >= 2:
        if task["status"] == "queued":
            task = set_status(conn, task, "awaiting_approval", actor)
        if task["status"] == "awaiting_approval":
            approvals.request(conn, task, actor, None, settings)
    return get(conn, task["id"])


def cancel(conn, task_id, actor: str, reason: str = "cancelled_by_user") -> dict:
    task = get(conn, task_id, lock=True)
    if task["status"] in TERMINAL:
        raise Conflict("Tâche déjà terminée", code="already_terminal")
    if task["status"] == "running":
        conn.execute("UPDATE tasks SET cancel_requested=true WHERE id=%s", (task["id"],))
        audit.record(conn, actor, "task.cancel_requested", "task", task["id"], task["correlation_id"])
        return get(conn, task["id"])
    approvals.invalidate_for_task(conn, task["id"], reason, actor)
    return set_status(conn, task, "cancelled", actor, error_code=reason)


def dependencies(conn, task_id) -> list[dict]:
    return conn.execute(
        """SELECT t.id, t.status, t.outputs, t.kind FROM task_dependencies d JOIN tasks t ON t.id=d.depends_on_id
           WHERE d.task_id=%s ORDER BY t.created_at""", (str(task_id),)).fetchall()
