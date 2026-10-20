"""Requêtes de lecture des cinq vues du Dashboard. Tout vient de la base ; rien n'est inventé."""
from __future__ import annotations


def executive(conn) -> dict:
    services = conn.execute("SELECT id, name, kind, status, checked_at, detail FROM services ORDER BY id").fetchall()
    counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) n FROM tasks GROUP BY status")}
    blocked = conn.execute(
        """SELECT id, kind, title, status, error_code, created_at FROM tasks
           WHERE status IN ('awaiting_approval','failed')
              OR (status='queued' AND queued_at < now() - interval '10 minutes')
           ORDER BY created_at DESC LIMIT 20""").fetchall()
    exp = conn.execute("""SELECT coalesce(sum(amount_cents) FILTER (WHERE documented),0) doc,
                                 coalesce(sum(amount_cents) FILTER (WHERE NOT documented),0) undoc
                          FROM ledger_entries WHERE kind='expense'""").fetchone()
    pay = conn.execute("SELECT coalesce(sum(amount_cents) FILTER (WHERE documented),0) s FROM ledger_entries WHERE kind='payment'").fetchone()
    prospects = conn.execute("SELECT count(*) n FROM prospects").fetchone()["n"]
    props = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) n FROM proposals GROUP BY status")}
    em = conn.execute("SELECT emergency_stop, stopped_at, reason FROM system_state WHERE id=1").fetchone()
    pend = conn.execute("SELECT count(*) n FROM approvals WHERE status='pending' AND expires_at>now()").fetchone()["n"]
    return {"services": services, "tasks_by_status": counts, "blocked_tasks": blocked,
            "expenses_documented_cents": exp["doc"], "expenses_undocumented_cents": exp["undoc"],
            "payments_documented_cents": pay["s"], "currency": "EUR",
            "pipeline": {"prospects": prospects, "proposals_by_status": props},
            "approvals_pending": pend, "emergency": em}


def forge(conn) -> dict:
    return {
        "mode": "SIMULATION",
        "repositories": conn.execute("SELECT id, name, url, status, imported_at FROM repositories ORDER BY name").fetchall(),
        "repository_status_counts": {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) n FROM repositories GROUP BY status")},
        "strategies": conn.execute("SELECT id, name, version, status, definition, created_at FROM strategy_versions ORDER BY created_at DESC LIMIT 50").fetchall(),
        "datasets": conn.execute("SELECT id, name, version, sha256, rows, provenance, created_at FROM dataset_versions ORDER BY created_at DESC LIMIT 50").fetchall(),
        "experiments": conn.execute(
            """SELECT e.id, e.status, e.mode, e.assumptions, e.metrics, e.created_at,
                      (e.report_md IS NOT NULL) AS has_report, s.name AS strategy, s.version AS strategy_version,
                      d.name AS dataset, d.version AS dataset_version
               FROM experiments e LEFT JOIN strategy_versions s ON s.id=e.strategy_version_id
               LEFT JOIN dataset_versions d ON d.id=e.dataset_version_id ORDER BY e.created_at DESC LIMIT 50""").fetchall(),
    }


def agency(conn) -> dict:
    return {
        "prospects": conn.execute("SELECT id, name, sector, documented_issues, is_fictional, created_at FROM prospects ORDER BY created_at DESC LIMIT 100").fetchall(),
        "proposals": conn.execute(
            """SELECT p.id, p.prospect_id, p.status, p.review, p.version, p.created_at, p.task_id, pr.name AS prospect
               FROM proposals p JOIN prospects pr ON pr.id=p.prospect_id ORDER BY p.created_at DESC LIMIT 100""").fetchall(),
        "pending_approvals": conn.execute(
            """SELECT a.id, a.action, a.task_id, a.expires_at, a.status FROM approvals a
               WHERE a.status='pending' AND a.expires_at>now() ORDER BY a.requested_at""").fetchall(),
    }


def mesh(conn) -> dict:
    """Graphe construit uniquement à partir de lignes existantes : services, agents, tâches, dépendances."""
    nodes, edges = [], []
    for s in conn.execute("SELECT id, name, status FROM services"):
        nodes.append({"id": f"service:{s['id']}", "type": "service", "label": s["name"], "status": s["status"]})
    for a in conn.execute("SELECT id, name, service_id, enabled FROM agents"):
        nodes.append({"id": f"agent:{a['id']}", "type": "agent", "label": a["name"], "status": "enabled" if a["enabled"] else "disabled"})
        if a["service_id"]:
            edges.append({"source": f"agent:{a['id']}", "target": f"service:{a['service_id']}", "kind": "runs_on"})
    tasks = conn.execute("SELECT id, kind, title, owner, status FROM tasks ORDER BY created_at DESC LIMIT 60").fetchall()
    ids = {str(t["id"]) for t in tasks}
    agents = {r["id"] for r in conn.execute("SELECT id FROM agents")}
    for t in tasks:
        nodes.append({"id": f"task:{t['id']}", "type": "task", "label": t["title"], "status": t["status"], "kind": t["kind"]})
        if t["owner"] in agents:
            edges.append({"source": f"task:{t['id']}", "target": f"agent:{t['owner']}", "kind": "owned_by"})
    for d in conn.execute("SELECT task_id, depends_on_id FROM task_dependencies"):
        if str(d["task_id"]) in ids and str(d["depends_on_id"]) in ids:
            edges.append({"source": f"task:{d['task_id']}", "target": f"task:{d['depends_on_id']}", "kind": "depends_on"})
    return {"nodes": nodes, "edges": edges}
