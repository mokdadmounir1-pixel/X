"""Omni-Box : commande naturelle → intention structurée → paramètres → permissions → aperçu → validation → tâche.
Le modèle PROPOSE une intention ; ce module DÉCIDE. Aucune commande système ni code n'est jamais exécuté."""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID
from pydantic import Field, model_validator
from . import tasks as T
from .errors import Forbidden, Invalid
from .kinds import P
from .llm import LLM, parse_json_object

MAX_TEXT = 500


class NoParams(P):
    pass


class CreateTaskP(P):
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(default="", max_length=500)


class DraftP(P):
    prospect_id: UUID


class ExperimentP(P):
    fast: int = Field(default=10, ge=2, le=50)
    slow: int = Field(default=50, ge=5, le=200)
    fee_bps: float = Field(default=2.0, ge=0, le=50)
    seed: int = Field(default=42, ge=0, le=10_000_000)

    @model_validator(mode="after")
    def _o(self):
        if self.slow <= self.fast:
            raise ValueError("slow doit être supérieur à fast")
        return self


class StopP(P):
    reason: str = Field(min_length=3, max_length=300)


@dataclass(frozen=True)
class IntentSpec:
    model: type[P]
    min_role: str
    requires_approval: bool
    doc: str


INTENTS: dict[str, IntentSpec] = {
    "show_status": IntentSpec(NoParams, "lecture", False, "Afficher l'état des services, tâches et approbations"),
    "create_task": IntentSpec(CreateTaskP, "operateur", False, "Créer une note-tâche : params title, text"),
    "draft_proposal": IntentSpec(DraftP, "operateur", False, "Préparer un brouillon de proposition : params prospect_id"),
    "run_demo_experiment": IntentSpec(ExperimentP, "operateur", False,
                                      "Lancer un backtest de DÉMONSTRATION : params fast, slow, fee_bps, seed"),
    "request_stop_workflows": IntentSpec(StopP, "operateur", True, "Demander l'arrêt des workflows : param reason"),
}

SYSTEM_PROMPT = (
    "Tu convertis une commande en une intention JSON. Réponds UNIQUEMENT par un objet JSON "
    '{"intent": <nom>, "params": {...}}. Intentions autorisées :\n'
    + "\n".join(f"- {k}: {v.doc}" for k, v in INTENTS.items())
    + '\nSi la demande ne correspond à aucune intention, réponds {"intent": "unsupported", "params": {}}. '
      "Tu n'exécutes rien, tu ne produis aucune commande système."
)


def interpret(llm: LLM, text: str) -> dict:
    text = (text or "").strip()
    if not text or len(text) > MAX_TEXT:
        raise Invalid(f"Commande vide ou trop longue (max {MAX_TEXT} caractères)", code="bad_command_text")
    data = parse_json_object(llm.chat(SYSTEM_PROMPT, text, json_mode=True))
    intent, params = data.get("intent"), data.get("params", {})
    if not isinstance(intent, str) or not isinstance(params, dict):
        raise Invalid("Intention mal formée", code="bad_intent_shape")
    return {"intent": intent, "params": params}


def validate(principal, intent: str, params: dict) -> tuple[IntentSpec, dict]:
    spec = INTENTS.get(intent)
    if spec is None:
        raise Forbidden(f"Intention non autorisée : {intent[:60]!r}", code="intent_not_allowed")
    principal.require(spec.min_role)
    try:
        clean = spec.model(**params).model_dump(mode="json")
    except Exception as e:  # noqa: BLE001
        raise Invalid(f"Paramètres refusés : {e}", code="invalid_params") from e
    return spec, clean


def status_summary(conn) -> dict:
    by = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) n FROM tasks GROUP BY status")}
    sv = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) n FROM services GROUP BY status")}
    pend = conn.execute("SELECT count(*) n FROM approvals WHERE status='pending' AND expires_at>now()").fetchone()["n"]
    em = conn.execute("SELECT emergency_stop FROM system_state WHERE id=1").fetchone()["emergency_stop"]
    return {"tasks": by, "services": sv, "approvals_pending": pend, "emergency_stop": em}


def preview(conn, intent: str, spec: IntentSpec, clean: dict) -> dict:
    out = {"intent": intent, "params": clean, "requires_approval": spec.requires_approval, "mode": "SIMULATION"}
    if intent == "show_status":
        out["effect"] = "Lecture seule"
    elif intent == "create_task":
        out["effect"] = "Crée 1 tâche interne « note »"
    elif intent == "draft_proposal":
        out["effect"] = "Crée 2 tâches : brouillon puis contrôle. Aucun envoi ; une demande d'approbation sera créée après contrôle."
    elif intent == "run_demo_experiment":
        out["effect"] = "Crée 3 tâches : données synthétiques versionnées → backtest avec frais → rapport. SIMULATION, non validé."
    elif intent == "request_stop_workflows":
        n = conn.execute("SELECT count(*) n FROM tasks WHERE status IN ('draft','queued','awaiting_approval')").fetchone()["n"]
        r = conn.execute("SELECT count(*) n FROM tasks WHERE status='running'").fetchone()["n"]
        out["effect"] = (f"Après approbation du Fondateur : annule {n} tâche(s) non démarrée(s), "
                         f"demande l'arrêt de {r} tâche(s) en cours.")
    return out


def execute(conn, principal, intent: str, params: dict, confirm: bool, settings, correlation_id) -> dict:
    spec, clean = validate(principal, intent, params)
    if intent == "show_status":
        return {"intent": intent, "result": status_summary(conn)}
    if not confirm:
        raise Invalid("Confirmation explicite requise après l'aperçu", code="confirmation_required")
    common = dict(created_by=principal.username, correlation_id=correlation_id, settings=settings)
    made: list[dict] = []
    if intent == "create_task":
        made.append(T.create(conn, kind="note", title=clean["title"], params={"text": clean["text"] or clean["title"]}, **common))
    elif intent == "draft_proposal":
        d = T.create(conn, kind="agency.draft_proposal", title="Brouillon de proposition",
                     params={"prospect_id": clean["prospect_id"]}, **common)
        r = T.create(conn, kind="agency.review", title="Contrôle du brouillon",
                     params={"prospect_id": clean["prospect_id"]}, depends_on=[d["id"]], **common)
        made += [d, r]
    elif intent == "run_demo_experiment":
        seed = clean["seed"]
        d = T.create(conn, kind="quant.dataset", title="Données synthétiques versionnées", params={"seed": seed}, **common)
        b = T.create(conn, kind="quant.backtest", title="Backtest avec frais",
                     params={"seed": seed, "fast": clean["fast"], "slow": clean["slow"], "fee_bps": clean["fee_bps"]},
                     depends_on=[d["id"]], **common)
        r = T.create(conn, kind="quant.report", title="Rapport (SIMULATION)", params={}, depends_on=[b["id"]], **common)
        made += [d, b, r]
    elif intent == "request_stop_workflows":
        made.append(T.create(conn, kind="stop_workflows", title="Arrêt des workflows", params={"reason": clean["reason"]}, **common))
    return {"intent": intent, "tasks": [{"id": str(t["id"]), "kind": t["kind"], "status": t["status"]} for t in made],
            "correlation_id": str(correlation_id)}
