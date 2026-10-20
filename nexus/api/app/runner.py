"""Exécuteur de tâches : claim atomique, délai d'attente, reprises limitées, arrêt d'urgence respecté."""
from __future__ import annotations
import concurrent.futures as cf
import logging, threading, time
from . import approvals, audit, tasks as T
from .db import J, tx
from .errors import Forbidden, LLMUnavailable, NexusError
from .handlers import Ctx, HANDLERS, TaskCancelled

log = logging.getLogger("nexus.runner")
_POOL = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="nexus-task")
TRANSIENT = (LLMUnavailable,)


def _claim(conn):
    if T.emergency_active(conn, lock=True):
        return None
    cands = conn.execute(
        """SELECT * FROM tasks WHERE status='queued' AND (not_before IS NULL OR not_before <= now())
           ORDER BY queued_at LIMIT 25 FOR UPDATE SKIP LOCKED""").fetchall()
    for t in cands:
        deps = T.dependencies(conn, t["id"])
        if any(d["status"] in ("failed", "cancelled") for d in deps):
            T.set_status(conn, t, "failed", "system", error_code="dependency_failed",
                         error_message="Une dépendance a échoué ou été annulée")
            continue
        if any(d["status"] != "succeeded" for d in deps):
            continue
        if t["auth_level"] >= 2:
            try:
                approvals.consume_for_execution(conn, t)
            except Forbidden as e:
                audit.record(conn, "system", "task.start_denied", "task", t["id"], t["correlation_id"], "denied",
                             {"code": e.code})
                T.set_status(conn, t, "failed", "system", error_code=e.code, error_message=e.message)
                continue
        conn.execute("UPDATE tasks SET attempts=attempts+1, started_at=coalesce(started_at, now()) WHERE id=%s", (t["id"],))
        row = T.set_status(conn, conn.execute("SELECT * FROM tasks WHERE id=%s", (t["id"],)).fetchone(), "running", "system")
        conn.execute("INSERT INTO workflow_runs(task_id, attempt, status, correlation_id) VALUES (%s,%s,'running',%s)",
                     (t["id"], row["attempts"], t["correlation_id"]))
        return row
    return None


def run_next(settings, llm) -> bool:
    """Exécute au plus une tâche. Retourne True si une tâche a été traitée."""
    with tx(settings.database_url) as conn:
        task = _claim(conn)
    if task is None:
        return False
    ctx = Ctx(task, settings, llm)
    fut = _POOL.submit(HANDLERS[task["kind"]], ctx)
    err: Exception | None = None
    outputs: dict | None = None
    cancelled = False
    try:
        outputs = fut.result(timeout=task["timeout_s"])
    except cf.TimeoutError:
        err = NexusError(f"Délai dépassé ({task['timeout_s']} s)", code="timeout")
        with tx(settings.database_url) as c:
            c.execute("UPDATE tasks SET cancel_requested=true WHERE id=%s", (task["id"],))
    except TaskCancelled:
        cancelled = True
    except Exception as e:  # noqa: BLE001 - toute erreur de handler devient un état d'échec explicite
        err = e if isinstance(e, NexusError) else NexusError(f"{type(e).__name__}: {e}", code="handler_error")
    _finalize(settings, task, outputs, err, cancelled)
    return True


def _finalize(settings, task, outputs, err, cancelled):
    with tx(settings.database_url) as c:
        cur = T.get(c, task["id"], lock=True)
        if cur["status"] != "running":     # résultat tardif après timeout/annulation : ignoré
            return
        if cancelled:
            T.set_status(c, cur, "cancelled", "system", error_code="cancelled")
            status = "cancelled"
        elif err is None:
            T.set_status(c, cur, "succeeded", "system", outputs=outputs or {}, error_code=None, error_message=None)
            status = "succeeded"
        elif isinstance(err, TRANSIENT) and cur["attempts"] < cur["max_attempts"]:
            delay = settings.retry_backoff_s * cur["attempts"]
            T.set_status(c, cur, "queued", "system", error_code=err.code, error_message=err.message,
                         not_before=None)
            c.execute("UPDATE tasks SET not_before = now() + make_interval(secs => %s) WHERE id=%s", (delay, cur["id"]))
            status = "retry"
        else:
            T.set_status(c, cur, "failed", "system", error_code=err.code, error_message=err.message)
            status = "failed"
        c.execute("""UPDATE workflow_runs SET status=%s, finished_at=now(), error_code=%s
                     WHERE task_id=%s AND attempt=%s""",
                  (status, getattr(err, "code", None), cur["id"], cur["attempts"]))


def recover_orphans(settings) -> int:
    """Tâches « running » sans exécution vivante (redémarrage ou panne du processus) : échec explicite.
    Elles ne sont PAS relancées automatiquement : une action non idempotente pourrait être dupliquée."""
    n = 0
    with tx(settings.database_url) as c:
        rows = c.execute(
            """SELECT t.* FROM tasks t WHERE t.status='running' AND NOT EXISTS (
                 SELECT 1 FROM workflow_runs w WHERE w.task_id=t.id AND w.status='running'
                   AND w.started_at > now() - make_interval(secs => t.timeout_s * 2))
               FOR UPDATE SKIP LOCKED""").fetchall()
        for t in rows:
            T.set_status(c, t, "failed", "system", error_code="interrupted",
                         error_message="Interrompue (redémarrage ou panne) ; non relancée automatiquement pour éviter un doublon")
            c.execute("UPDATE workflow_runs SET status='failed', finished_at=now(), error_code='interrupted' WHERE task_id=%s AND status='running'", (t["id"],))
            n += 1
    return n


def drain(settings, llm, limit: int = 100) -> int:
    n = 0
    while n < limit and run_next(settings, llm):
        n += 1
    return n


class Worker(threading.Thread):
    def __init__(self, settings, llm):
        super().__init__(daemon=True, name="nexus-worker")
        self.settings, self.llm, self._stop_evt = settings, llm, threading.Event()

    def run(self):
        last_probe = 0.0
        while not self._stop_evt.is_set():
            try:
                if time.monotonic() - last_probe > 30:
                    last_probe = time.monotonic()
                    from . import services
                    recover_orphans(self.settings)
                    services.probe_all(self.settings)
                if not run_next(self.settings, self.llm):
                    self._stop_evt.wait(0.5)
            except Exception:  # noqa: BLE001
                log.exception("worker error")
                self._stop_evt.wait(2.0)

    def stop(self):
        self._stop_evt.set()
