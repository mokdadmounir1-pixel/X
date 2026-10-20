"""Critères d'acceptation de l'ordre d'exécution 001, §8. Un test par critère, sur un vrai PostgreSQL."""
import json, subprocess, uuid
import psycopg
import pytest
from psycopg.rows import dict_row
from app import runner
from app.config import Settings
from app.handlers import HANDLERS
from app.migrate import migrate
from app.security import RedactFilter, check_password_policy
from app.errors import Invalid
from tests.conftest import FakeLLM, PG_BIN, _as_pg


def q(env, sql, *a):
    with psycopg.connect(env.url, row_factory=dict_row, autocommit=True) as c:
        cur = c.execute(sql, a or None)
        return cur.fetchall() if cur.description else []


def drain(env, llm=None):
    return runner.drain(env.settings, llm or env.llm)


def omni(env, headers, intent, params, key=None, confirm=True):
    h = dict(headers)
    if key:
        h["Idempotency-Key"] = key
    return env.client.post("/api/omnibox/execute", json={"intent": intent, "params": params, "confirm": confirm}, headers=h)


# ---- 1. Démarrage / migrations
def test_migrations_apply_once_and_are_idempotent(env):
    assert migrate(env.url) == []                     # déjà appliquées par la fixture
    assert len(q(env, "SELECT * FROM schema_migrations")) == 2
    assert q(env, "SELECT count(*) n FROM users WHERE username NOT LIKE '%1'")[0]["n"] == 0


def test_no_default_account_and_weak_passwords_refused(dburl):
    migrate(dburl)
    with psycopg.connect(dburl) as c:
        assert c.execute("SELECT count(*) FROM users").fetchone()[0] == 0     # aucun compte par défaut
    for bad in ("court", "password1234", "nexus-nexus-nexus", "aaaaaaaaaaaa", "fondateur1"):
        with pytest.raises(Invalid):
            check_password_policy("fondateur1", bad)
    check_password_policy("fondateur1", "Une-Phrase-De-Passe-Correcte-9")


# ---- 2. Une tâche se suit de bout en bout (journal + Dashboard)
def test_task_end_to_end_in_journal_and_dashboard(env):
    r = env.client.post("/api/tasks", json={"kind": "note", "title": "essai", "params": {"text": "bonjour"}},
                        headers={**env.O, "X-Correlation-Id": "11111111-1111-4111-8111-111111111111"})
    assert r.status_code == 200 and r.json()["status"] == "queued"
    tid = r.json()["id"]
    assert drain(env) == 1
    t = env.client.get(f"/api/tasks/{tid}", headers=env.L).json()
    assert t["status"] == "succeeded" and t["outputs"] == {"echo": "bonjour"}
    assert t["correlation_id"] == "11111111-1111-4111-8111-111111111111"
    assert [e["action"] for e in t["events"]] == ["task.draft", "task.queued", "task.running", "task.succeeded"]
    assert t["runs"][0]["status"] == "succeeded"
    mesh = env.client.get("/api/views/mesh", headers=env.L).json()
    assert any(n["id"] == f"task:{tid}" and n["status"] == "succeeded" for n in mesh["nodes"])
    assert any(e["source"] == f"task:{tid}" and e["target"] == "agent:operateur" for e in mesh["edges"])
    ex = env.client.get("/api/views/executive", headers=env.L).json()
    assert ex["tasks_by_status"]["succeeded"] == 1
    assert env.client.get("/api/audit/verify", headers=env.L).json()["ok"] is True


# ---- 3. Persistance après redémarrage
def test_data_persists_after_database_restart(env):
    env.client.post("/api/tasks", json={"kind": "note", "title": "persist", "params": {"text": "x"}}, headers=env.O)
    drain(env)
    env.cluster.stop()
    env.cluster.start()
    client2 = env.make_client()
    h = env.login("lecteur1", client2)
    tasks = client2.get("/api/tasks", headers=h).json()
    assert [t["title"] for t in tasks] == ["persist"] and tasks[0]["status"] == "succeeded"
    assert client2.get("/api/audit/verify", headers=h).json()["ok"]


# ---- 4. Sauvegarde restaurée
def test_backup_restore_roundtrip(env):
    env.client.post("/api/tasks", json={"kind": "note", "title": "avant-sauvegarde", "params": {"text": "x"}}, headers=env.O)
    drain(env)
    dump = env.cluster.dir / "backup.sql"
    _as_pg([f"{PG_BIN}/pg_dump", "-h", "127.0.0.1", "-p", str(env.cluster.port), "-U", "postgres", "-f", str(dump), env.url.rsplit("/", 1)[1]])
    name = "restored_" + uuid.uuid4().hex[:8]
    with psycopg.connect(env.cluster.url("postgres"), autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    _as_pg([f"{PG_BIN}/psql", "-h", "127.0.0.1", "-p", str(env.cluster.port), "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-q", "-f", str(dump), name])
    with psycopg.connect(env.cluster.url(name), row_factory=dict_row) as r, psycopg.connect(env.url, row_factory=dict_row) as o:
        for table in ("tasks", "audit_events", "users", "services", "approvals"):
            assert r.execute(f"SELECT count(*) n FROM {table}").fetchone() == o.execute(f"SELECT count(*) n FROM {table}").fetchone()
        assert r.execute("SELECT verify_audit_chain() v").fetchone()["v"] is None
        assert r.execute("SELECT title FROM tasks").fetchone()["title"] == "avant-sauvegarde"
        with pytest.raises(psycopg.errors.RaiseException):
            r.execute("UPDATE audit_events SET actor='x'")       # l'immuabilité survit à la restauration


# ---- 5. Commande interdite refusée côté serveur
def test_forbidden_commands_refused_server_side(env):
    evil = FakeLLM(lambda s, u: json.dumps({"intent": "run_shell", "params": {"cmd": "rm -rf /"}}))
    c = env.make_client(evil)
    r = c.post("/api/omnibox/interpret", json={"text": "supprime tout"}, headers=env.O)
    assert r.status_code == 403 and r.json()["error"] == "intent_not_allowed"
    assert omni(env, env.O, "run_shell", {"cmd": "rm -rf /"}).status_code == 403          # contournement du modèle
    assert omni(env, env.O, "create_task", {"title": "a", "cmd": "rm -rf /"}).status_code == 422
    assert omni(env, env.L, "create_task", {"title": "a"}).status_code == 403             # rôle Lecture
    assert env.client.post("/api/tasks", json={"kind": "stop_workflows", "title": "x", "params": {"reason": "abc"}},
                           headers=env.O).status_code == 403                               # type non créable
    assert env.client.post("/api/tasks", json={"kind": "shell", "title": "x", "params": {}}, headers=env.O).status_code == 403
    assert env.client.post("/api/tasks", json={"kind": "note", "title": "x", "params": {"text": "a"}}).status_code == 401
    denied = q(env, "SELECT action FROM audit_events WHERE outcome='denied'")
    assert {"omnibox.refused", "request.denied"} <= {d["action"] for d in denied}
    assert q(env, "SELECT count(*) n FROM tasks")[0]["n"] == 0                              # rien n'a été créé


def test_omnibox_requires_preview_confirmation_and_valid_params(env):
    ok = FakeLLM(lambda s, u: json.dumps({"intent": "run_demo_experiment", "params": {"fast": 10, "slow": 50}}))
    c = env.make_client(ok)
    prev = c.post("/api/omnibox/interpret", json={"text": "lance une expérience"}, headers=env.O).json()
    assert prev["requires_approval"] is False and "SIMULATION" in prev["effect"]
    assert q(env, "SELECT count(*) n FROM tasks")[0]["n"] == 0                              # l'aperçu ne crée rien
    assert omni(env, env.O, "run_demo_experiment", {"fast": 10, "slow": 50}, confirm=False).status_code == 422
    assert omni(env, env.O, "run_demo_experiment", {"fast": 50, "slow": 10}).status_code == 422
    assert omni(env, env.O, "run_demo_experiment", {"fast": 10, "slow": 50}).status_code == 200


# ---- 6. Approbation expirée ou modifiée refusée
def _stop_task(env):
    r = omni(env, env.O, "request_stop_workflows", {"reason": "essai de test"})
    assert r.status_code == 200 and r.json()["tasks"][0]["status"] == "awaiting_approval"
    tid = r.json()["tasks"][0]["id"]
    ap = q(env, "SELECT id FROM approvals WHERE task_id=%s", tid)[0]["id"]
    return tid, str(ap)


def test_only_founder_decides_and_expired_approval_refused(env):
    tid, ap = _stop_task(env)
    assert env.client.post(f"/api/approvals/{ap}/decide", json={"decision": "approve"}, headers=env.O).status_code == 403
    q(env, "UPDATE approvals SET expires_at = now() - interval '1 minute' WHERE id=%s", ap)
    r = env.client.post(f"/api/approvals/{ap}/decide", json={"decision": "approve"}, headers=env.F)
    assert r.status_code == 409 and r.json()["error"] == "approval_expired"
    assert q(env, "SELECT status FROM approvals WHERE id=%s", ap)[0]["status"] == "expired"
    assert drain(env) == 0 and q(env, "SELECT status FROM tasks WHERE id=%s", tid)[0]["status"] == "awaiting_approval"
    # nouvelle demande, valable
    assert env.client.post(f"/api/tasks/{tid}/request-approval", json={"ttl_minutes": 30}, headers=env.O).status_code == 200
    ap2 = q(env, "SELECT id FROM approvals WHERE task_id=%s AND status='pending'", tid)[0]["id"]
    assert env.client.post(f"/api/approvals/{ap2}/decide", json={"decision": "approve"}, headers=env.F).status_code == 200
    drain(env)
    assert q(env, "SELECT status FROM tasks WHERE id=%s", tid)[0]["status"] == "succeeded"


def test_approval_expiring_before_execution_blocks_start(env):
    tid, ap = _stop_task(env)
    assert env.client.post(f"/api/approvals/{ap}/decide", json={"decision": "approve"}, headers=env.F).status_code == 200
    q(env, "UPDATE approvals SET expires_at = now() - interval '1 second' WHERE id=%s", ap)
    drain(env)
    t = q(env, "SELECT status, error_code FROM tasks WHERE id=%s", tid)[0]
    assert t == {"status": "failed", "error_code": "approval_expired"}


def test_modified_params_invalidate_approval(env):
    tid, ap = _stop_task(env)
    env.client.post(f"/api/approvals/{ap}/decide", json={"decision": "approve"}, headers=env.F)
    r = env.client.patch(f"/api/tasks/{tid}/params", json={"params": {"reason": "autre motif"}}, headers=env.O)
    assert r.status_code == 200 and r.json()["status"] == "awaiting_approval" and r.json()["version"] == 2
    assert q(env, "SELECT status FROM approvals WHERE id=%s", ap)[0]["status"] == "invalidated"
    assert drain(env) == 0                                                                  # rien ne part
    ap2 = q(env, "SELECT id FROM approvals WHERE task_id=%s AND status='pending'", tid)[0]["id"]
    assert str(ap2) != ap


def test_params_tampered_in_database_refused_at_start(env):
    tid, ap = _stop_task(env)
    env.client.post(f"/api/approvals/{ap}/decide", json={"decision": "approve"}, headers=env.F)
    q(env, """UPDATE tasks SET params='{"reason":"modifié hors API"}' WHERE id=%s""", tid)   # contournement : pas de nouveau hash
    drain(env)
    t = q(env, "SELECT status, error_code FROM tasks WHERE id=%s", tid)[0]
    assert t == {"status": "failed", "error_code": "approval_params_changed"}
    assert q(env, "SELECT count(*) n FROM audit_events WHERE action='task.start_denied'")[0]["n"] == 1


def test_approval_is_single_use(env):
    tid, ap = _stop_task(env)
    env.client.post(f"/api/approvals/{ap}/decide", json={"decision": "approve"}, headers=env.F)
    drain(env)
    assert q(env, "SELECT status FROM approvals WHERE id=%s", ap)[0]["status"] == "consumed"
    assert env.client.post(f"/api/approvals/{ap}/decide", json={"decision": "approve"}, headers=env.F).status_code == 409


# ---- 7. Une requête répétée ne duplique pas l'action
def test_repeated_request_does_not_duplicate(env):
    body = {"kind": "note", "title": "une seule fois", "params": {"text": "x"}}
    h = {**env.O, "Idempotency-Key": "abc-123"}
    a = env.client.post("/api/tasks", json=body, headers=h).json()
    b = env.client.post("/api/tasks", json=body, headers=h).json()
    assert a["id"] == b["id"] and b["idempotent_replay"] is True
    assert q(env, "SELECT count(*) n FROM tasks")[0]["n"] == 1
    assert env.client.post("/api/tasks", json={**body, "title": "autre"}, headers=h).json()["error"] == "idempotency_key_reuse"
    r1 = omni(env, env.O, "run_demo_experiment", {"fast": 10, "slow": 50}, key="k-omni").json()
    r2 = omni(env, env.O, "run_demo_experiment", {"fast": 10, "slow": 50}, key="k-omni").json()
    assert r1["tasks"] == r2["tasks"] and q(env, "SELECT count(*) n FROM tasks WHERE kind LIKE 'quant.%'")[0]["n"] == 3


# ---- 8. Arrêt d'urgence
def test_emergency_stop_blocks_new_starts_and_reports_categories(env):
    q(env, "INSERT INTO external_actions(kind,target) VALUES ('test_marker','déjà fait avant l''arrêt')")
    queued = env.client.post("/api/tasks", json={"kind": "note", "title": "en file", "params": {"text": "a"}}, headers=env.O).json()["id"]
    running = env.client.post("/api/tasks", json={"kind": "note", "title": "en cours", "params": {"text": "b"}}, headers=env.O).json()["id"]
    q(env, "UPDATE tasks SET status='running', started_at=now() WHERE id=%s", running)
    stop_task, _ = _stop_task(env)
    r = env.client.post("/api/emergency/stop", json={"reason": "test d'arrêt"}, headers=env.O)
    assert r.status_code == 200 and r.json()["emergency_stop"] is True
    rep = r.json()["report"]
    assert {t["id"] for t in rep["cancelled"]} == {queued, stop_task}
    assert [t["id"] for t in rep["still_running"]] == [running]
    assert [e["kind"] for e in rep["external_actions_already_done"]] == ["test_marker"]
    assert q(env, "SELECT cancel_requested FROM tasks WHERE id=%s", running)[0]["cancel_requested"] is True
    # plus rien ne démarre ni ne se crée
    assert env.client.post("/api/tasks", json={"kind": "note", "title": "x", "params": {"text": "a"}}, headers=env.O).status_code == 423
    assert omni(env, env.O, "run_demo_experiment", {"fast": 10, "slow": 50}).status_code == 423
    assert drain(env) == 0
    # persistant : un nouveau processus voit le même état
    c2 = env.make_client()
    assert c2.get("/api/emergency", headers=env.login("lecteur1", c2)).json()["emergency_stop"] is True
    # réarmement : Fondateur seul, confirmation explicite
    assert env.client.post("/api/emergency/rearm", json={"confirm": "REARMER"}, headers=env.O).status_code == 403
    assert env.client.post("/api/emergency/rearm", json={"confirm": "oui"}, headers=env.F).status_code == 403
    assert env.client.post("/api/emergency/rearm", json={"confirm": "REARMER"}, headers=env.F).status_code == 200
    assert env.client.post("/api/tasks", json={"kind": "note", "title": "x", "params": {"text": "a"}}, headers=env.O).status_code == 200


# ---- 9. Panne d'Ollama = état d'échec explicite
def test_ollama_outage_gives_explicit_failure(env):
    down = FakeLLM(down=True)
    tid = env.client.post("/api/tasks", json={"kind": "llm_summarize", "title": "résumé", "params": {"text": "un texte"}}, headers=env.O).json()["id"]
    runner.drain(env.settings, down)
    t = env.client.get(f"/api/tasks/{tid}", headers=env.L).json()
    assert t["status"] == "failed" and t["error_code"] == "llm_unavailable" and "Ollama" in t["error_message"]
    assert t["attempts"] == 2                                    # reprises limitées à max_attempts
    assert [r["status"] for r in t["runs"]] == ["retry", "failed"]
    c = env.make_client(down)
    r = c.post("/api/omnibox/interpret", json={"text": "état"}, headers=env.O)
    assert r.status_code == 503 and r.json()["error"] == "llm_unavailable"
    assert q(env, "SELECT count(*) n FROM audit_events WHERE action='omnibox.failed'")[0]["n"] == 1


def test_timeout_and_dependency_failure(env, monkeypatch):
    import time
    monkeypatch.setitem(HANDLERS, "note", lambda ctx: time.sleep(2) or {})
    a = env.client.post("/api/tasks", json={"kind": "note", "title": "lente", "params": {"text": "a"}}, headers=env.O).json()["id"]
    q(env, "UPDATE tasks SET timeout_s=1 WHERE id=%s", a)
    drain(env)
    assert q(env, "SELECT status, error_code FROM tasks WHERE id=%s", a)[0] == {"status": "failed", "error_code": "timeout"}
    d = q(env, """INSERT INTO tasks(kind,title,owner,params,params_hash,correlation_id,created_by,status,queued_at)
                  VALUES ('note','dépend','operateur','{"text":"z"}','h',gen_random_uuid(),'t','queued',now()) RETURNING id""")[0]["id"]
    q(env, "INSERT INTO task_dependencies VALUES (%s,%s)", d, a)
    drain(env)
    assert q(env, "SELECT status, error_code FROM tasks WHERE id=%s", d)[0] == {"status": "failed", "error_code": "dependency_failed"}


# ---- 10. Parcours de démonstration, sans action externe
def test_agency_demo_journey_no_external_action(env):
    body = {"name": "Boulangerie Fictive SARL", "sector": "commerce", "documented_issues": ["Site lent sur mobile", "Pas de page contact"]}
    r = env.client.post("/api/demo/agency", json=body, headers=env.O)
    assert r.status_code == 200
    assert env.client.post("/api/demo/agency", json={**body, "is_fictional": False}, headers=env.O).status_code == 422
    drain(env)
    ag = env.client.get("/api/views/agency", headers=env.L).json()
    prop = ag["proposals"][0]
    assert prop["status"] == "awaiting_approval" and prop["review"]["passed"] is True
    assert len(ag["pending_approvals"]) == 1
    assert "€" not in env.client.get(f"/api/proposals/{prop['id']}", headers=env.L).json()["body_md"]
    env.client.post(f"/api/approvals/{ag['pending_approvals'][0]['id']}/decide", json={"decision": "approve"}, headers=env.F)
    drain(env)
    assert q(env, "SELECT status FROM proposals")[0]["status"] == "approved_not_sent"
    send = q(env, "SELECT outputs FROM tasks WHERE kind='agency.send_proposal'")[0]["outputs"]
    assert send["sent"] is False
    assert q(env, "SELECT count(*) n FROM external_actions")[0]["n"] == 0


def test_agency_review_blocks_prices_and_guarantees(env):
    body = {"name": "Client Fictif", "documented_issues": ["Budget 5000 € annoncé garanti"]}
    env.client.post("/api/demo/agency", json=body, headers=env.O)
    drain(env)
    assert q(env, "SELECT status, error_code FROM tasks WHERE kind='agency.review'")[0] == {"status": "failed", "error_code": "review_failed"}
    assert q(env, "SELECT count(*) n FROM approvals")[0]["n"] == 0
    assert q(env, "SELECT status FROM proposals")[0]["status"] == "draft"


def test_quant_demo_journey_is_simulation_with_provenance(env):
    r = env.client.post("/api/demo/quant", json={"seed": 7}, headers=env.O)
    assert r.status_code == 200
    drain(env)
    f = env.client.get("/api/views/forge", headers=env.L).json()
    assert f["mode"] == "SIMULATION"
    ex = f["experiments"][0]
    assert ex["mode"] == "SIMULATION" and ex["has_report"] and ex["assumptions"]["optimized"] is False
    assert ex["assumptions"]["fee_bps"] == 2.0 and ex["metrics"]["full"]["trades"] > 0
    ds = f["datasets"][0]
    assert ds["provenance"]["type"] == "synthetic" and len(ds["sha256"]) == 64
    rep = env.client.get(f"/api/experiments/{ex['id']}/report", headers=env.L).json()["report_md"]
    assert "n'est pas une stratégie validée" in rep and ds["sha256"] in rep and "Hypothèses" in rep
    env.client.post("/api/demo/quant", json={"seed": 7}, headers=env.O)               # même graine → même jeu de données versionné
    drain(env)
    assert q(env, "SELECT count(*) n FROM dataset_versions")[0]["n"] == 1
    assert q(env, "SELECT count(*) n FROM external_actions")[0]["n"] == 0


def test_costs_matter_in_backtest():
    from app import quant_engine as qe
    p = qe.make_prices(3, 1500)
    free = qe.backtest(p, 10, 50, 0, 0)
    paid = qe.backtest(p, 10, 50, 25, 25)
    assert paid["net_return_pct"] < free["net_return_pct"] and paid["cost_drag_pct_of_equity"] > 0


def test_council_keeps_disagreements_and_grants_no_rights(env):
    def reply(system, user):
        if "JSON" in system:
            return json.dumps({"agreements": ["risque réel"], "disagreements": ["taille de l'échantillon", "horizon"],
                               "open_questions": ["données ?"], "recommendation": "attendre", "grants_rights": True})
        return "avis"
    llm = FakeLLM(reply)
    cid = env.make_client(llm).post("/api/demo/council", json={"question": "Faut-il passer en réel ?"}, headers=env.O).json()["session_id"]
    runner.drain(env.settings, llm)
    s = env.client.get(f"/api/council/{cid}", headers=env.L).json()
    assert s["proposal"] and s["counter"] and len(s["synthesis"]["disagreements"]) == 2
    assert s["synthesis"]["grants_rights"] is False and s["grants_rights"] is False      # le modèle ne peut pas s'en octroyer
    with pytest.raises(psycopg.errors.CheckViolation):
        q(env, "UPDATE council_sessions SET grants_rights=true")


def test_ceo_commitments_are_optional_and_local(env):
    d = env.client.get("/api/ceo", headers=env.L).json()
    assert d["optional"] is True and [c["kind"] for c in d["commitments"]] == ["decision_prioritaire", "action_livree", "revue_fin_journee"]
    assert all(c["text"] is None for c in d["commitments"])
    assert env.client.put("/api/ceo/decision_prioritaire", json={"text": "Livrer le socle", "done": True}, headers=env.L).status_code == 403
    assert env.client.put("/api/ceo/decision_prioritaire", json={"text": "Livrer le socle", "done": True}, headers=env.O).status_code == 200
    assert env.client.get("/api/ceo", headers=env.L).json()["commitments"][0]["done"] is True


# ---- Journal, secrets, rôles, dépôts
def test_audit_is_append_only_and_tampering_is_detected(env):
    env.client.post("/api/tasks", json={"kind": "note", "title": "t", "params": {"text": "a"}}, headers=env.O)
    for sql in ("UPDATE audit_events SET actor='x'", "DELETE FROM audit_events", "TRUNCATE audit_events"):
        with pytest.raises(psycopg.errors.RaiseException):
            q(env, sql)
    q(env, "ALTER TABLE audit_events DISABLE TRIGGER audit_no_update")           # un administrateur de la base peut contourner...
    q(env, "UPDATE audit_events SET actor='falsifié' WHERE seq = (SELECT min(seq) FROM audit_events)")
    q(env, "ALTER TABLE audit_events ENABLE TRIGGER audit_no_update")
    v = env.client.get("/api/audit/verify", headers=env.L).json()
    assert v["ok"] is False and v["first_bad_seq"] is not None                     # ...mais l'altération est détectée


def test_secrets_are_redacted_from_logs():
    s = RedactFilter.redact("login ok Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123 password=Hunter2xx "
                            "url=postgresql://nexus:SuperSecret@db:5432/n")
    assert "abcdefghijklmnop" not in s and "Hunter2" not in s and "SuperSecret" not in s and s.count("[REDACTED]") == 3


def test_login_failures_audited_and_throttled(env):
    for _ in range(5):
        assert env.client.post("/api/auth/login", json={"username": "operateur1", "password": "mauvais-mot-de-passe"}).status_code == 401
    assert env.client.post("/api/auth/login", json={"username": "operateur1", "password": "Un-Mot-De-Passe-Solide-1"}).status_code == 403
    assert q(env, "SELECT count(*) n FROM audit_events WHERE action='auth.login_failed'")[0]["n"] == 5


def test_roles_matrix(env):
    assert env.client.get("/api/tasks", headers=env.L).status_code == 200
    assert env.client.post("/api/tasks", json={"kind": "note", "title": "x", "params": {"text": "a"}}, headers=env.L).status_code == 403
    assert env.client.post("/api/ledger", json={"kind": "expense", "amount_cents": 100, "label": "x"}, headers=env.O).status_code == 403
    assert env.client.post("/api/ledger", json={"kind": "expense", "amount_cents": 1000, "label": "VPS", "documented": True}, headers=env.F).status_code == 422
    assert env.client.post("/api/ledger", json={"kind": "expense", "amount_cents": 1000, "label": "VPS", "documented": True, "document_ref": "FAC-1"}, headers=env.F).status_code == 200
    assert env.client.get("/api/views/executive", headers=env.L).json()["expenses_documented_cents"] == 1000
    env.client.post("/api/auth/logout", headers=env.L)
    assert env.client.get("/api/tasks", headers=env.L).status_code == 401


def test_repository_import_marks_downloaded_not_audited(env, tmp_path):
    from app import repos
    inv = tmp_path / "inv.json"
    inv.write_text(json.dumps({"depots": [{"name": "alpha", "url": "https://x/alpha"}, {"nom": "beta"}, "gamma"]}))
    with psycopg.connect(env.url, row_factory=dict_row) as c:
        assert repos.import_inventory(c, inv) == {"created": 3, "skipped": 0}
        assert repos.import_inventory(c, inv) == {"created": 0, "skipped": 3}
        c.commit()
    f = env.client.get("/api/views/forge", headers=env.L).json()
    assert f["repository_status_counts"] == {"downloaded_unaudited": 3}


def test_incident_improvement_loop_enforces_order_and_independent_review(env):
    i = env.client.post("/api/incidents", json={"severity": "high", "title": "Ollama muet"}, headers=env.O).json()["id"]
    url = f"/api/incidents/{i}"
    assert env.client.patch(url, json={"status": "fixed", "corrective_action": "x"}, headers=env.O).status_code == 409
    assert env.client.patch(url, json={"status": "root_cause"}, headers=env.O).status_code == 422
    for body in ({"status": "root_cause", "root_cause": "délai trop court"}, {"status": "fixed", "corrective_action": "délai 60 s"},
                 {"status": "tested", "tests_ref": "test_ollama_outage"}):
        assert env.client.patch(url, json=body, headers=env.O).status_code == 200
    assert env.client.patch(url, json={"status": "reviewed", "reviewed_by": "operateur1"}, headers=env.O).status_code == 403
    assert env.client.patch(url, json={"status": "reviewed", "reviewed_by": "fondateur1"}, headers=env.O).status_code == 200


def test_connectors_are_prepared_but_disabled():
    from app.connectors import REGISTRY, ConnectorDisabled
    assert set(REGISTRY) == {"crawl4ai", "browser-use", "ccxt", "mt5"}
    assert all(not c.enabled for c in REGISTRY.values())
    assert REGISTRY["mt5"].runs_in_container is False
    for call in (REGISTRY["ccxt"].place_order, REGISTRY["mt5"].place_order, lambda: REGISTRY["crawl4ai"].fetch("https://x"),
                 lambda: REGISTRY["browser-use"].run("x")):
        with pytest.raises(ConnectorDisabled):
            call()


def test_service_probe_reports_real_state(env):
    r = env.client.post("/api/services/probe", headers=env.O)
    assert r.status_code == 200
    st = {s["id"]: s["status"] for s in r.json()}
    assert st["api"] == "up" and st["postgres"] == "up"
    assert st["ollama"] == "down" and st["n8n"] == "down" and st["mt5"] == "disabled"   # rien n'écoute dans les tests
    assert env.client.post("/api/services/probe", headers=env.L).status_code == 403


def test_two_runners_never_execute_the_same_task_twice(env):
    import threading
    for i in range(6):
        env.client.post("/api/tasks", json={"kind": "note", "title": f"t{i}", "params": {"text": str(i)}}, headers=env.O)
    done = []
    def go():
        done.append(runner.drain(env.settings, env.llm))
    ths = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ths]; [t.join() for t in ths]
    assert sum(done) == 6
    assert q(env, "SELECT count(*) n FROM workflow_runs")[0]["n"] == 6
    assert q(env, "SELECT max(attempts) m FROM tasks")[0]["m"] == 1


def test_task_interrupted_by_restart_is_failed_explicitly_not_replayed(env):
    tid = env.client.post("/api/tasks", json={"kind": "note", "title": "coupée", "params": {"text": "a"}}, headers=env.O).json()["id"]
    q(env, "UPDATE tasks SET status='running', attempts=1, started_at=now() - interval '10 minutes' WHERE id=%s", tid)
    q(env, "INSERT INTO workflow_runs(task_id, attempt, status, started_at) VALUES (%s,1,'running', now() - interval '10 minutes')", tid)
    assert runner.recover_orphans(env.settings) == 1
    t = q(env, "SELECT status, error_code FROM tasks WHERE id=%s", tid)[0]
    assert t == {"status": "failed", "error_code": "interrupted"}
    assert q(env, "SELECT status FROM workflow_runs WHERE task_id=%s", tid)[0]["status"] == "failed"
    assert drain(env) == 0                                                   # jamais relancée seule
    live = env.client.post("/api/tasks", json={"kind": "note", "title": "vivante", "params": {"text": "b"}}, headers=env.O).json()["id"]
    q(env, "UPDATE tasks SET status='running' WHERE id=%s", live)
    q(env, "INSERT INTO workflow_runs(task_id, attempt, status) VALUES (%s,1,'running')", live)
    assert runner.recover_orphans(env.settings) == 0                         # une exécution récente n'est pas touchée
