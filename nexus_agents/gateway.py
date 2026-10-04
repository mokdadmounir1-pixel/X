"""Passerelle de modeles : routage, assainissement, budget reserve avant tout appel payant."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from . import injection
from .models import ModelUnavailable
from .trace import Trace

ROUTES = {
    "score_lead": "local", "extract_fact": "local", "draft_message": "local",
    "revise_message": "local", "classify_reply": "local",
    "final_check": "cloud", "deep_check": "cloud", "closing": "cloud",
}


@dataclass
class GatewayResult:
    ok: bool
    code: str
    output: Any = None
    model: Optional[str] = None
    route: Optional[str] = None
    cost_cents: int = 0
    degraded: bool = False
    injections: list = field(default_factory=list)


class ModelGateway:
    NAME = "Passerelle de modèles"

    def __init__(self, db, trace: Trace, local, cloud=None, qualified_tasks=None, prompts=None):
        self.db, self.trace, self.local, self.cloud = db, trace, local, cloud
        self.prompts = prompts      # PromptStore : prompt de l'agent relu en base a chaque appel (None = prompt integre au modele)
        # None = pas de controle (demonstration). Sinon, ensemble des taches dont le modele local a ete QUALIFIE par le banc ;
        # les autres sont refusees (pause), jamais envoyees au cloud par defaut.
        self.qualified_tasks = None if qualified_tasks is None else set(qualified_tasks)
        # Resultats cloud deja payes, par cle d'idempotence : une relance apres incident ne refait pas (et ne refacture pas) l'appel.
        # LIMITE : en memoire, donc perdu si le processus redemarre. A persister avant tout usage avec un vrai fournisseur.
        self._cloud_cache: dict = {}

    def run(self, task: str, payload: dict, *, caller: str, external_keys=(), allow_cloud=False,
            est_cents: Optional[int] = None, category="operations", idem: Optional[str] = None,
            lead_ref: Optional[str] = None) -> GatewayResult:
        route = ROUTES.get(task)
        if route is None:
            self.trace.emit(caller, self.NAME, "refus", f"{task}: tâche inconnue", ok=False, code="unknown_task")
            return GatewayResult(False, "unknown_task")
        payload = dict(payload)
        findings: list = []
        for key in external_keys:                       # le texte externe est une donnee, jamais une consigne
            if isinstance(payload.get(key), str):
                payload[key], f = injection.scan(payload[key])
                findings += [{**x, "field": key} for x in f]
        sp = self._system_prompt(task)
        self.trace.emit(caller, self.NAME, "demande", f"{task} → route {route}" + (f" · prompt {sp[0]} v{sp[1]}" if sp else ""),
                        route=route, external_fields=list(external_keys), prompt_agent=sp[0] if sp else None,
                        prompt_version=sp[1] if sp else None, lead_ref=lead_ref)
        for x in findings:
            self.trace.emit(self.NAME, caller, "injection", f"phrase retirée ({x['rule']}) : « {x['sentence'][:80]} »",
                            ok=False, code="tentative_injection", rule=x["rule"])
        if route == "local":
            if self.qualified_tasks is not None and task not in self.qualified_tasks:
                self.trace.emit(self.NAME, caller, "refus", f"{task}: modèle local non qualifié pour cette tâche → pause", ok=False, code="model_not_qualified")
                return GatewayResult(False, "model_not_qualified", route="local", degraded=True, injections=findings)
            return self._call(self.local, task, payload, caller, "local", findings, 0, sp)
        # ---- route cloud : jamais sans autorisation explicite ni budget reserve
        if not allow_cloud:
            self.trace.emit(self.NAME, caller, "refus", f"{task}: cloud non autorisé pour cet appel", ok=False, code="cloud_not_allowed")
            return GatewayResult(False, "cloud_not_allowed", degraded=True, injections=findings)
        if self.cloud is None:
            self.trace.emit(self.NAME, caller, "refus", f"{task}: aucun modèle cloud branché", ok=False, code="cloud_unavailable")
            return GatewayResult(False, "cloud_unavailable", degraded=True, injections=findings)
        if not est_cents or est_cents <= 0:
            self.trace.emit(self.NAME, caller, "refus", f"{task}: coût inconnu, appel refusé", ok=False, code="unknown_cost")
            return GatewayResult(False, "unknown_cost", degraded=True, injections=findings)
        idem = idem or "gw:" + hashlib.sha256(json.dumps([task, payload], sort_keys=True, default=str).encode()).hexdigest()[:24]
        if idem in self._cloud_cache:
            cached = self._cloud_cache[idem]
            self.trace.emit(self.NAME, caller, "réutilisé", f"{task}: résultat déjà payé réutilisé, aucun nouvel appel facturé", ok=True, code="cache_hit")
            return cached
        # api=True : soumis au plafond QUOTIDIEN. La reserve prioritaire n'est accordee que par la base, d'apres le score
        # enregistre du lead et la tache (final_check / closing) : ce que l'appelant declare ne compte pas.
        res = self.db.reserve(idem, category, est_cents, f"{task} pour {caller}", task=task, lead_ref=lead_ref, api=True)
        if not res.ok:
            self.trace.emit(self.NAME, caller, "refus", f"{task}: budget refusé ({res.code}) — aucune requête cloud émise",
                            ok=False, code=res.code, cost_cents=0)
            return GatewayResult(False, res.code, degraded=True, injections=findings)
        try:
            out = self._call(self.cloud, task, payload, caller, "cloud", findings, est_cents, sp)
        except Exception:
            self.db.release(res.id)
            raise
        if not out.ok:
            self.db.release(res.id)
            return out
        if res.code == "ok_priority_reserve":
            self.trace.emit(self.NAME, "Noyau Nexus", "reserve_prioritaire",
                            f"{task} financé par la réserve prioritaire (plafond quotidien atteint, lead {lead_ref} éligible)", ok=True,
                            code="ok_priority_reserve", lead_ref=lead_ref)
        self.db.settle(res.id, out.cost_cents)
        self._cloud_cache[idem] = out
        return out

    def _system_prompt(self, task):
        if self.prompts is None:
            return None
        from .prompts import TASK_AGENT
        agent = TASK_AGENT.get(task)
        ap = self.prompts.active(agent) if agent else None
        return (agent, ap.version, ap.prompt) if ap else None

    def _call(self, model, task, payload, caller, route, findings, est, sp=None) -> GatewayResult:
        try:
            out = model.generate(task, payload, system_prompt=sp[2]) if sp else model.generate(task, payload)
        except ModelUnavailable as exc:
            self.trace.emit(self.NAME, caller, "erreur", f"{model.name}: {exc}", ok=False, code="model_unavailable")
            return GatewayResult(False, "model_unavailable", route=route, degraded=True, injections=findings)
        self.trace.emit(self.NAME, model.name, "inference", f"{task} ({out.tokens_in}→{out.tokens_out} jetons)",
                        simulated=out.simulated, route=route)
        self.trace.emit(model.name, caller, "réponse", f"{task} terminé", ok=True, code="ok", cost_cents=out.cost_cents,
                        reserved_cents=est)
        return GatewayResult(True, "ok", out.value, out.model, route, out.cost_cents, False, findings)
