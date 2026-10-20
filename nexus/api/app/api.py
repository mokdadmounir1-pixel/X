from __future__ import annotations
import datetime as dt
import logging, uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from . import approvals, audit, emergency, omnibox, repos, runner, services as services_mod, tasks as T, views
from .canon import canonical, sha256_hex
from .config import Settings
from .db import J, tx
from .errors import Conflict, Forbidden, Invalid, NexusError, NotFound, Unauthorized
from .kinds import KINDS
from .llm import LLM, OllamaClient
from .security import (LoginThrottle, Principal, RedactFilter, check_password_policy, hash_password,
                       new_token, principal_from_token, token_hash, verify_password)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(In):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TaskIn(In):
    kind: str
    title: str = Field(min_length=1, max_length=200)
    params: dict = {}


class ParamsIn(In):
    params: dict


class TtlIn(In):
    ttl_minutes: int | None = None


class DecideIn(In):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=500)


class OmniIn(In):
    text: str = Field(max_length=2000)


class OmniExecIn(In):
    intent: str = Field(max_length=60)
    params: dict = {}
    confirm: bool = False


class StopIn(In):
    reason: str = Field(min_length=3, max_length=300)


class RearmIn(In):
    confirm: str


class ProspectIn(In):
    name: str = Field(min_length=1, max_length=120)
    sector: str | None = Field(default=None, max_length=120)
    contact_info: dict = {}
    documented_issues: list[str] = Field(default=[], max_length=20)
    is_fictional: bool = True


class AgencyDemoIn(ProspectIn):
    pass


class QuantDemoIn(In):
    seed: int = Field(default=42, ge=0, le=10_000_000)
    fast: int = Field(default=10, ge=2, le=50)
    slow: int = Field(default=50, ge=5, le=200)
    fee_bps: float = Field(default=2.0, ge=0, le=50)


class CouncilIn(In):
    question: str = Field(min_length=5, max_length=1000)


class CeoIn(In):
    text: str | None = Field(default=None, max_length=300)
    done: bool = False


class LedgerIn(In):
    kind: Literal["expense", "payment"]
    amount_cents: int = Field(gt=0, le=10**10)
    label: str = Field(min_length=1, max_length=200)
    documented: bool = False
    document_ref: str | None = Field(default=None, max_length=300)


class IncidentIn(In):
    severity: Literal["low", "medium", "high", "critical"]
    title: str = Field(min_length=3, max_length=200)


class IncidentStep(In):
    status: Literal["root_cause", "fixed", "tested", "reviewed", "deployed", "closed"]
    root_cause: str | None = Field(default=None, max_length=2000)
    corrective_action: str | None = Field(default=None, max_length=2000)
    tests_ref: str | None = Field(default=None, max_length=300)
    reviewed_by: str | None = Field(default=None, max_length=100)


INCIDENT_ORDER = ["open", "root_cause", "fixed", "tested", "reviewed", "deployed", "closed"]


def create_app(settings: Settings | None = None, llm: LLM | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    llm = llm or OllamaClient(settings.ollama_url, settings.ollama_model, settings.llm_timeout_s)
    logging.getLogger().addFilter(RedactFilter())
    for h in logging.getLogger().handlers:
        h.addFilter(RedactFilter())
    throttle = LoginThrottle()
    worker = {"t": None}

    @asynccontextmanager
    async def lifespan(app):
        if settings.worker_enabled:
            runner.recover_orphans(settings)
            worker["t"] = runner.Worker(settings, app.state.llm)
            worker["t"].start()
        yield
        if worker["t"]:
            worker["t"].stop()

    app = FastAPI(title="NEXUS API", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings, app.state.llm = settings, llm
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH", "PUT"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Correlation-Id"])

    @app.middleware("http")
    async def headers(request: Request, call_next):
        request.state.correlation_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
        request.state.actor = "anonymous"
        resp = await call_next(request)
        resp.headers["X-Correlation-Id"] = request.state.correlation_id
        resp.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.exception_handler(NexusError)
    async def nexus_error(request: Request, exc: NexusError):
        if isinstance(exc, (Forbidden, Unauthorized)) or exc.code in ("emergency_stop",):
            try:    # le refus est journalisé dans une transaction séparée (la principale est annulée)
                with tx(settings.database_url) as c:
                    audit.record(c, request.state.actor, "request.denied", "http", request.url.path,
                                 request.state.correlation_id, "denied",
                                 {"method": request.method, "code": exc.code, "message": exc.message[:200]})
            except Exception:  # noqa: BLE001
                logging.getLogger("nexus").exception("audit du refus impossible")
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message,
                                                             "correlation_id": request.state.correlation_id})

    def auth(request: Request, minimum: str = "lecture") -> Principal:
        h = request.headers.get("Authorization", "")
        token = h[7:] if h.lower().startswith("bearer ") else None
        with tx(settings.database_url) as c:
            p = principal_from_token(c, token)
        request.state.actor = p.username
        p.require(minimum)
        return p

    def idem(request, conn, p: Principal, payload, fn):
        key = request.headers.get("Idempotency-Key")
        if not key:
            return fn()
        if len(key) > 128:
            raise Invalid("Idempotency-Key trop longue", code="bad_idempotency_key")
        rh = sha256_hex(canonical({"path": request.url.path, "body": payload}))
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{p.username}|{key}",))
        row = conn.execute("SELECT * FROM idempotency_keys WHERE actor=%s AND key=%s", (p.username, key)).fetchone()
        if row:
            if row["request_hash"] != rh:
                raise Invalid("Idempotency-Key déjà utilisée avec une autre requête", code="idempotency_key_reuse")
            return {**row["response"], "idempotent_replay": True}
        result = jsonable_encoder(fn())
        conn.execute("INSERT INTO idempotency_keys(actor,key,request_hash,status_code,response) VALUES (%s,%s,%s,200,%s)",
                     (p.username, key, rh, J(result)))
        return result

    api = APIRouter(prefix="/api")

    @api.get("/health")
    def health():
        try:
            with tx(settings.database_url) as c:
                c.execute("SELECT 1")
            return {"status": "ok", "version": "0.1.0"}
        except Exception:  # noqa: BLE001
            return JSONResponse(status_code=503, content={"status": "db_down"})

    # ---------- Auth ----------
    @api.post("/auth/login")
    def login(body: LoginIn, request: Request):
        throttle.check(body.username)
        with tx(settings.database_url) as c:
            u = c.execute("SELECT * FROM users WHERE username=%s AND active", (body.username,)).fetchone()
            ok = bool(u) and verify_password(body.password, u["password_hash"])
            if not ok:
                throttle.fail(body.username)
                audit.record(c, body.username[:64], "auth.login_failed", "user", None, request.state.correlation_id, "denied")
                c.commit()
                raise Unauthorized("Identifiants invalides")
            tok = new_token()
            c.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (%s,%s, now() + make_interval(hours => %s))",
                      (token_hash(tok), u["id"], settings.session_ttl_h))
            audit.record(c, u["username"], "auth.login", "user", u["id"], request.state.correlation_id)
        return {"token": tok, "role": u["role"], "username": u["username"], "expires_in_h": settings.session_ttl_h}

    @api.post("/auth/logout")
    def logout(request: Request):
        p = auth(request)
        tok = request.headers["Authorization"][7:]
        with tx(settings.database_url) as c:
            c.execute("UPDATE sessions SET revoked=true WHERE token_hash=%s", (token_hash(tok),))
            audit.record(c, p.username, "auth.logout", "user", p.user_id, request.state.correlation_id)
        return {"ok": True}

    @api.get("/auth/me")
    def me(request: Request):
        p = auth(request)
        return {"username": p.username, "role": p.role}

    # ---------- Services ----------
    @api.get("/services")
    def services(request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            return c.execute("SELECT * FROM services ORDER BY id").fetchall()

    @api.post("/services/probe")
    def probe(request: Request):
        p = auth(request, "operateur")
        return services_mod.probe_all(settings, p.username, request.state.correlation_id)

    # ---------- Tâches ----------
    @api.get("/tasks")
    def list_tasks(request: Request, status: str | None = None, limit: int = 100):
        auth(request)
        limit = max(1, min(limit, 500))
        with tx(settings.database_url) as c:
            if status:
                return c.execute("SELECT * FROM tasks WHERE status=%s ORDER BY created_at DESC LIMIT %s", (status, limit)).fetchall()
            return c.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()

    @api.get("/tasks/{task_id}")
    def get_task(task_id: uuid.UUID, request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            t = T.get(c, task_id)
            t["dependencies"] = [str(d["id"]) for d in T.dependencies(c, task_id)]
            t["runs"] = c.execute("SELECT * FROM workflow_runs WHERE task_id=%s ORDER BY started_at", (str(task_id),)).fetchall()
            t["events"] = c.execute("""SELECT seq, ts, actor, action, outcome FROM audit_events
                                       WHERE entity_type='task' AND entity_id=%s OR correlation_id=%s ORDER BY seq""",
                                    (str(task_id), str(t["correlation_id"]))).fetchall()
            return t

    @api.post("/tasks")
    def create_task(body: TaskIn, request: Request):
        p = auth(request, "operateur")
        spec = KINDS.get(body.kind)
        if spec is None or not spec.direct:
            raise Forbidden(f"Type de tâche non créable directement : {body.kind}", code="kind_not_allowed")
        with tx(settings.database_url) as c:
            return idem(request, c, p, body.model_dump(), lambda: T.create(
                c, kind=body.kind, title=body.title, params=body.params, created_by=p.username,
                correlation_id=request.state.correlation_id, settings=settings))

    @api.patch("/tasks/{task_id}/params")
    def patch_params(task_id: uuid.UUID, body: ParamsIn, request: Request):
        p = auth(request, "operateur")
        with tx(settings.database_url) as c:
            return T.update_params(c, task_id, body.params, p.username, settings)

    @api.post("/tasks/{task_id}/cancel")
    def cancel_task(task_id: uuid.UUID, request: Request):
        p = auth(request, "operateur")
        with tx(settings.database_url) as c:
            return T.cancel(c, task_id, p.username)

    # ---------- Approbations ----------
    @api.post("/tasks/{task_id}/request-approval")
    def request_approval(task_id: uuid.UUID, body: TtlIn, request: Request):
        p = auth(request, "operateur")
        with tx(settings.database_url) as c:
            t = T.get(c, task_id, lock=True)
            if t["status"] != "awaiting_approval":
                raise Conflict("La tâche n'attend pas d'approbation", code="not_awaiting")
            live = c.execute("SELECT 1 FROM approvals WHERE task_id=%s AND status='pending' AND expires_at>now()", (t["id"],)).fetchone()
            if live:
                raise Conflict("Une demande valide existe déjà", code="already_pending")
            return approvals.request(c, t, p.username, body.ttl_minutes, settings)

    @api.get("/approvals")
    def list_approvals(request: Request, status: str | None = None):
        auth(request)
        with tx(settings.database_url) as c:
            q = "SELECT a.*, t.title, t.kind FROM approvals a JOIN tasks t ON t.id=a.task_id"
            if status:
                return c.execute(q + " WHERE a.status=%s ORDER BY a.requested_at DESC LIMIT 200", (status,)).fetchall()
            return c.execute(q + " ORDER BY a.requested_at DESC LIMIT 200").fetchall()

    @api.post("/approvals/{approval_id}/decide")
    def decide(approval_id: uuid.UUID, body: DecideIn, request: Request):
        p = auth(request, "fondateur")
        with tx(settings.database_url) as c:
            try:
                return approvals.decide(c, approval_id, p, body.decision, body.note)
            except Conflict:
                c.commit()   # conserve l'expiration/invalidation constatée et sa trace
                raise

    # ---------- Omni-Box ----------
    @api.post("/omnibox/interpret")
    def omni_interpret(body: OmniIn, request: Request):
        p = auth(request, "lecture")
        corr = request.state.correlation_id
        try:
            proposed = omnibox.interpret(request.app.state.llm, body.text)
        except NexusError as e:
            with tx(settings.database_url) as c:
                audit.record(c, p.username, "omnibox.failed", "omnibox", None, corr, "error", {"code": e.code})
                c.execute("INSERT INTO workflow_runs(source,status,error_code,finished_at,correlation_id) VALUES ('omnibox','failed',%s,now(),%s)", (e.code, corr))
            raise
        try:
            spec, clean = omnibox.validate(p, proposed["intent"], proposed["params"])
        except NexusError as e:
            with tx(settings.database_url) as c:
                audit.record(c, p.username, "omnibox.refused", "omnibox", None, corr, "denied",
                             {"intent": str(proposed["intent"])[:60], "code": e.code})
            raise
        with tx(settings.database_url) as c:
            prev = omnibox.preview(c, proposed["intent"], spec, clean)
            audit.record(c, p.username, "omnibox.interpreted", "omnibox", None, corr, details={"intent": proposed["intent"]})
        return prev

    @api.post("/omnibox/execute")
    def omni_execute(body: OmniExecIn, request: Request):
        p = auth(request, "lecture")
        corr = request.state.correlation_id
        try:
            with tx(settings.database_url) as c:
                return idem(request, c, p, body.model_dump(), lambda: omnibox.execute(
                    c, p, body.intent, body.params, body.confirm, settings, corr))
        except Forbidden as e:
            with tx(settings.database_url) as c:
                audit.record(c, p.username, "omnibox.refused", "omnibox", None, corr, "denied",
                             {"intent": body.intent[:60], "code": e.code})
            raise

    # ---------- Arrêt d'urgence ----------
    @api.get("/emergency")
    def emergency_status(request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            return emergency.status(c)

    @api.post("/emergency/stop")
    def emergency_stop(body: StopIn, request: Request):
        p = auth(request, "operateur")
        with tx(settings.database_url) as c:
            return emergency.engage(c, p, body.reason)

    @api.post("/emergency/rearm")
    def emergency_rearm(body: RearmIn, request: Request):
        p = auth(request, "fondateur")
        with tx(settings.database_url) as c:
            return emergency.rearm(c, p, body.confirm)

    # ---------- Journal ----------
    @api.get("/audit")
    def audit_list(request: Request, limit: int = 200, action: str | None = None, outcome: str | None = None):
        auth(request)
        limit = max(1, min(limit, 1000))
        with tx(settings.database_url) as c:
            q, a = "SELECT seq, ts, actor, action, entity_type, entity_id, correlation_id, outcome, details, hash FROM audit_events", []
            w = []
            if action:
                w.append("action LIKE %s"); a.append(action + "%")
            if outcome:
                w.append("outcome=%s"); a.append(outcome)
            return c.execute(q + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY seq DESC LIMIT %s", (*a, limit)).fetchall()

    @api.get("/audit/verify")
    def audit_verify(request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            return audit.verify(c)

    # ---------- Vues ----------
    @api.get("/views/executive")
    def v_exec(request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            return views.executive(c)

    @api.get("/views/forge")
    def v_forge(request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            return views.forge(c)

    @api.get("/views/agency")
    def v_agency(request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            return views.agency(c)

    @api.get("/views/mesh")
    def v_mesh(request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            return views.mesh(c)

    @api.get("/experiments/{experiment_id}/report")
    def experiment_report(experiment_id: uuid.UUID, request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            r = c.execute("SELECT id, mode, report_md, assumptions, metrics FROM experiments WHERE id=%s", (str(experiment_id),)).fetchone()
            if not r:
                raise NotFound("Expérience introuvable")
            return r

    @api.get("/proposals/{proposal_id}")
    def proposal(proposal_id: uuid.UUID, request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            r = c.execute("SELECT * FROM proposals WHERE id=%s", (str(proposal_id),)).fetchone()
            if not r:
                raise NotFound("Proposition introuvable")
            return r

    # ---------- Parcours de démonstration ----------
    @api.post("/demo/agency")
    def demo_agency(body: AgencyDemoIn, request: Request):
        p = auth(request, "operateur")
        if not body.is_fictional:
            raise Invalid("v0.1 : seuls les prospects fictifs sont acceptés", code="real_prospect_refused")
        corr = request.state.correlation_id
        with tx(settings.database_url) as c:
            def go():
                pr = c.execute("""INSERT INTO prospects(name, sector, contact_info, documented_issues, is_fictional)
                                  VALUES (%s,%s,%s,%s,true) RETURNING id""",
                               (body.name, body.sector, J(body.contact_info), J(body.documented_issues))).fetchone()
                audit.record(c, p.username, "prospect.imported", "prospect", pr["id"], corr, details={"fictional": True})
                kw = dict(created_by=p.username, correlation_id=corr, settings=settings)
                a = T.create(c, kind="agency.analyze", title="Analyse du prospect", params={"prospect_id": str(pr["id"])}, **kw)
                d = T.create(c, kind="agency.draft_proposal", title="Brouillon de proposition", params={"prospect_id": str(pr["id"])}, depends_on=[a["id"]], **kw)
                r = T.create(c, kind="agency.review", title="Contrôle du brouillon", params={"prospect_id": str(pr["id"])}, depends_on=[d["id"]], **kw)
                return {"prospect_id": str(pr["id"]), "correlation_id": corr,
                        "tasks": [str(a["id"]), str(d["id"]), str(r["id"])],
                        "note": "Aucun envoi externe. Après le contrôle, une demande d'approbation apparaît."}
            return idem(request, c, p, body.model_dump(), go)

    @api.post("/demo/quant")
    def demo_quant(body: QuantDemoIn, request: Request):
        p = auth(request, "operateur")
        with tx(settings.database_url) as c:
            return idem(request, c, p, body.model_dump(), lambda: omnibox.execute(
                c, p, "run_demo_experiment", body.model_dump(), True, settings, request.state.correlation_id))

    @api.post("/demo/council")
    def demo_council(body: CouncilIn, request: Request):
        p = auth(request, "operateur")
        corr = request.state.correlation_id
        with tx(settings.database_url) as c:
            def go():
                s = c.execute("INSERT INTO council_sessions(question) VALUES (%s) RETURNING id", (body.question,)).fetchone()
                kw = dict(created_by=p.username, correlation_id=corr, settings=settings)
                sid = str(s["id"])
                a = T.create(c, kind="council.role", title="Proposition", params={"session_id": sid, "role": "proposal"}, **kw)
                b = T.create(c, kind="council.role", title="Contre-analyse", params={"session_id": sid, "role": "counter"}, depends_on=[a["id"]], **kw)
                d = T.create(c, kind="council.synthesis", title="Synthèse (désaccords conservés)", params={"session_id": sid}, depends_on=[b["id"]], **kw)
                c.execute("UPDATE council_sessions SET task_id=%s WHERE id=%s", (d["id"], sid))
                return {"session_id": sid, "tasks": [str(a["id"]), str(b["id"]), str(d["id"])], "correlation_id": corr}
            return idem(request, c, p, body.model_dump(), go)

    @api.get("/council/{session_id}")
    def council_get(session_id: uuid.UUID, request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            r = c.execute("SELECT * FROM council_sessions WHERE id=%s", (str(session_id),)).fetchone()
            if not r:
                raise NotFound("Session introuvable")
            return r

    @api.get("/ceo")
    def ceo_get(request: Request, day: dt.date | None = None):
        auth(request)
        with tx(settings.database_url) as c:
            d = day or dt.date.today()
            rows = {r["kind"]: r for r in c.execute("SELECT * FROM ceo_commitments WHERE day=%s", (d,)).fetchall()}
            return {"day": d.isoformat(), "optional": True, "commitments": [
                {"kind": k, "text": rows.get(k, {}).get("text"), "done": rows.get(k, {}).get("done", False)}
                for k in ("decision_prioritaire", "action_livree", "revue_fin_journee")]}

    @api.put("/ceo/{kind}")
    def ceo_put(kind: Literal["decision_prioritaire", "action_livree", "revue_fin_journee"], body: CeoIn, request: Request):
        p = auth(request, "operateur")
        with tx(settings.database_url) as c:
            c.execute("""INSERT INTO ceo_commitments(day, kind, text, done) VALUES (current_date,%s,%s,%s)
                         ON CONFLICT (day, kind) DO UPDATE SET text=EXCLUDED.text, done=EXCLUDED.done, updated_at=now()""",
                      (kind, body.text, body.done))
            audit.record(c, p.username, "ceo.updated", "ceo", kind, request.state.correlation_id)
        return {"ok": True}

    # ---------- Comptabilité, incidents, dépôts ----------
    @api.post("/ledger")
    def ledger_add(body: LedgerIn, request: Request):
        p = auth(request, "fondateur")
        if body.documented and not body.document_ref:
            raise Invalid("Une entrée documentée exige une référence de pièce", code="document_ref_required")
        with tx(settings.database_url) as c:
            r = c.execute("""INSERT INTO ledger_entries(kind, amount_cents, label, documented, document_ref, created_by)
                             VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
                          (body.kind, body.amount_cents, body.label, body.documented, body.document_ref, p.username)).fetchone()
            audit.record(c, p.username, "ledger.added", "ledger", r["id"], request.state.correlation_id,
                         details={"kind": body.kind, "documented": body.documented})
            return r

    @api.get("/incidents")
    def incidents(request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            return c.execute("SELECT * FROM incidents ORDER BY created_at DESC LIMIT 200").fetchall()

    @api.post("/incidents")
    def incident_add(body: IncidentIn, request: Request):
        p = auth(request, "operateur")
        with tx(settings.database_url) as c:
            r = c.execute("INSERT INTO incidents(severity, title) VALUES (%s,%s) RETURNING *", (body.severity, body.title)).fetchone()
            audit.record(c, p.username, "incident.opened", "incident", r["id"], request.state.correlation_id, details={"severity": body.severity})
            return r

    @api.patch("/incidents/{incident_id}")
    def incident_step(incident_id: uuid.UUID, body: IncidentStep, request: Request):
        """Boucle d'amélioration : incident → cause racine → correctif → tests → revue → déploiement."""
        p = auth(request, "operateur")
        with tx(settings.database_url) as c:
            r = c.execute("SELECT * FROM incidents WHERE id=%s FOR UPDATE", (str(incident_id),)).fetchone()
            if not r:
                raise NotFound("Incident introuvable")
            if INCIDENT_ORDER.index(body.status) != INCIDENT_ORDER.index(r["status"]) + 1:
                raise Conflict(f"Étape suivante attendue : {INCIDENT_ORDER[INCIDENT_ORDER.index(r['status']) + 1] if r['status'] != 'closed' else 'aucune'}", code="bad_step")
            need = {"root_cause": body.root_cause, "fixed": body.corrective_action, "tested": body.tests_ref, "reviewed": body.reviewed_by}
            if body.status in need and not need[body.status]:
                raise Invalid(f"Champ requis pour l'étape {body.status}", code="step_field_required")
            if body.status == "reviewed" and body.reviewed_by == p.username:
                raise Forbidden("La revue doit être faite par une autre personne que l'opérateur de l'étape", code="self_review")
            c.execute("""UPDATE incidents SET status=%s, root_cause=coalesce(%s,root_cause), corrective_action=coalesce(%s,corrective_action),
                         tests_ref=coalesce(%s,tests_ref), reviewed_by=coalesce(%s,reviewed_by),
                         closed_at=CASE WHEN %s='closed' THEN now() END WHERE id=%s""",
                      (body.status, body.root_cause, body.corrective_action, body.tests_ref, body.reviewed_by, body.status, r["id"]))
            audit.record(c, p.username, f"incident.{body.status}", "incident", r["id"], request.state.correlation_id)
            return c.execute("SELECT * FROM incidents WHERE id=%s", (r["id"],)).fetchone()

    @api.get("/repositories")
    def repositories(request: Request):
        auth(request)
        with tx(settings.database_url) as c:
            return c.execute("SELECT * FROM repositories ORDER BY name").fetchall()

    app.include_router(api)
    if settings.web_dir and Path(settings.web_dir).is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
    return app
