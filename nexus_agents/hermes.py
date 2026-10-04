"""Hermes : l'operateur. Il enchaine les agents, applique les regles et escalade vers l'humain.

Il ne decide d'aucun engagement : il prepare, il fait respecter les garde-fous, il rend compte.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .agents import Analyste, Censeur, FondateurSimule, Lead, Redacteur, Setter, Sourcing, Transport
from .gateway import ModelGateway
from .trace import Trace


@dataclass
class CircuitBreaker:
    """Coupe-circuit de pipeline : ouvert, plus aucun brouillon n'est produit."""
    min_sent: int = 20
    max_bounce_rate: float = 0.05
    max_complaints: int = 2
    sent: int = 0
    bounces: int = 0
    complaints: int = 0

    def record(self, sent=0, bounces=0, complaints=0):
        self.sent += sent; self.bounces += bounces; self.complaints += complaints

    @property
    def reason(self):
        if self.complaints >= self.max_complaints:
            return f"{self.complaints} plaintes (seuil {self.max_complaints})"
        if self.sent >= self.min_sent and self.bounces / self.sent > self.max_bounce_rate:
            return f"rebonds {self.bounces}/{self.sent} (seuil {self.max_bounce_rate:.0%})"
        return None

    @property
    def is_open(self) -> bool:
        return self.reason is not None


class Hermes:
    NAME = "Hermes"

    def __init__(self, *, gateway: ModelGateway, db, trace: Trace, sourcing: Sourcing, analyste: Analyste,
                 redacteur: Redacteur, censeur: Censeur, fondateur: FondateurSimule, transport: Transport,
                 setter: Setter, breaker: CircuitBreaker | None = None):
        self.gw, self.db, self.trace = gateway, db, trace
        self.sourcing, self.analyste, self.redacteur = sourcing, analyste, redacteur
        self.censeur, self.fondateur, self.transport, self.setter = censeur, fondateur, transport, setter
        self.breaker = breaker or CircuitBreaker()
        self.outcomes: list[dict] = []
        self.leads: dict[str, Lead] = {}
        self.rejections: list[dict] = []     # materiau de la boucle d'evolution

    def _end(self, raw, status, detail="", **extra):
        out = {"lead": raw.get("id"), "company": raw.get("company"), "status": status, "detail": detail, **extra}
        self.outcomes.append(out)
        self.trace.emit(self.NAME, "Hermes", "issue", f"{raw.get('company')} → {status}" + (f" ({detail})" if detail else ""),
                        ok=status in ("sent", "approved"), code=status)
        return out

    def process_lead(self, raw: dict, *, model_quality="normal", cloud_check=False, deep_check=False) -> dict:
        t = self.trace
        t.ctx = {"lead": raw.get("id")}
        t.emit(self.NAME, self.NAME, "début", f"traitement de {raw.get('company')}")
        if self.breaker.is_open:
            self.db.notify_founder("circuit_open", f"{raw.get('id')}", f"Pipeline suspendu : {self.breaker.reason}")
            return self._end(raw, "pipeline_suspendu", self.breaker.reason)
        lead, why = self.sourcing.validate(raw)
        if lead is None:
            return self._end(raw, "écarté_sourcing", why)
        self.leads[lead.id] = lead
        if lead.flags:
            self.db.notify_founder("injection_attempt", lead.id,
                                   f"La page source de {lead.company} contenait des consignes ({', '.join(lead.flags)}) : ignorées, à vérifier à la main.")
            t.emit(self.NAME, "Fondateur (simulé)", "alerte", f"consigne cachée dans la source de {lead.company} : ignorée et signalée",
                   ok=False, code="tentative_injection")
        analysis = self.analyste.analyse(lead)
        if analysis is None:
            return self._end(raw, "écarté_analyse", "no_verifiable_fact")
        res = self.redacteur.draft(lead, analysis, model_quality)
        if res is None or not res.ok:
            return self._end(raw, "écarté_rédaction", res.code if res else "model_unavailable")
        mid, version = res.id, 1
        while True:
            verdict, issues, msg = self.censeur.review(mid)
            if verdict == "pass":
                break
            self.rejections.append({"lead": lead.id, "version": version, "issues": issues})
            if version >= 3:
                return self._end(raw, "pause_après_deux_corrections", "; ".join(issues))
            rev = self.redacteur.revise(mid, version, msg, issues)
            if not rev.ok:
                return self._end(raw, "révision_refusée", rev.code)
            mid, version = rev.id, version + 1
        marker = "sans vérification cloud"
        if cloud_check:
            r = self.gw.run("final_check", {"body": msg["body"]}, caller=self.NAME, allow_cloud=True, est_cents=150,
                            idem=f"final_check:{lead.id}:{mid}")
            marker = "vérifié par le modèle cloud (simulé)" if r.ok and r.output["ok"] else marker
        if deep_check:
            r = self.gw.run("deep_check", {"body": msg["body"]}, caller=self.NAME, allow_cloud=True, est_cents=3500,
                            category="research", idem=f"deep_check:{lead.id}")
            if not r.ok:
                self.db.notify_founder("needs_human", f"{lead.id}:deep", f"Vérification approfondie non faite ({r.code}) : décision à prendre sans elle.")
                t.emit(self.NAME, "Fondateur (simulé)", "alerte", f"vérification approfondie refusée par le budget ({r.code}) : mode dégradé signalé",
                       ok=False, code=r.code)
        t.emit(self.NAME, "Fondateur (simulé)", "dossier", f"message #{mid} prêt pour décision — {marker}", ok=True, code="ready_for_decision",
               marker=marker)
        if not self.fondateur.decide(lead, mid):
            return self._end(raw, "refusé_par_le_fondateur", marker, message_id=mid, version=version, flags=lead.flags)
        sent = self.transport.drain()
        self.breaker.record(sent=sent)
        return self._end(raw, "sent" if sent else "approved", marker, message_id=mid, version=version, flags=lead.flags)

    # ------------------------------------------------------------ file de taches durable
    def enqueue_lead(self, raw: dict, **options):
        t = self.trace
        t.ctx = {"lead": raw.get("id")}
        domain = (raw.get("email") or "").rsplit("@", 1)[-1].lower()
        res = self.db.enqueue(f"lead:{raw['id']}", "process_lead", {"raw": raw, "options": options}, f"domain:{domain}" if domain else None)
        if not res.ok and res.code == "duplicate":
            t.emit("Sourcing", "Hermes", "rejet", f"doublon (domaine {domain} déjà en file ou traité)", ok=False, code="duplicate")
            self._end(raw, "écarté_sourcing", "duplicate")
        else:
            t.emit(self.NAME, "Noyau Nexus", "file", f"tâche durable créée pour {raw.get('company')}", ok=res.ok, code=res.code)
        t.ctx = {}
        return res

    def enqueue_reply(self, raw: dict, text: str):
        key = hashlib.sha256(text.encode()).hexdigest()[:10]
        self.trace.ctx = {"lead": raw["id"]}
        res = self.db.enqueue(f"reply:{raw['id']}:{key}", "process_reply", {"raw": raw, "text": text})
        self.trace.ctx = {}
        return res

    @staticmethod
    def _lead_from_raw(raw: dict) -> Lead:
        return Lead(raw["id"], raw["company"], raw.get("contact_name", ""), raw["email"].lower(), raw.get("source_url", ""), raw.get("excerpt", ""))

    def run_pending(self, max_tasks: int = 100, retry_seconds: int = 60) -> int:
        """Execute les taches dues. Un echec est replanifie avec delai croissant, puis declare mort et signale."""
        done = 0
        for _ in range(max_tasks):
            task = self.db.claim_task()
            if task is None:
                break
            self.trace.ctx = {"lead": task.payload.get("raw", {}).get("id"), "task": task.task_id}
            self.trace.emit("Noyau Nexus", self.NAME, "tâche_reçue", f"tâche #{task.task_id} ({task.kind}), tentative {task.attempt}")
            try:
                if task.kind == "process_lead":
                    out = self.process_lead(task.payload["raw"], **task.payload.get("options", {}))
                    result = {"status": out["status"]}
                elif task.kind == "process_reply":
                    lead = self.leads.get(task.payload["raw"]["id"]) or self._lead_from_raw(task.payload["raw"])
                    result = {"label": self.setter.handle_reply(lead, task.payload["text"])}
                else:
                    raise ValueError(f"type de tâche inconnu: {task.kind}")
            except Exception as exc:     # noqa: BLE001 - toute panne doit etre rattrapee et rendue a la file
                r = self.db.fail_task(task.task_id, f"{type(exc).__name__}: {exc}", retry_seconds)
                self.trace.emit(self.NAME, self.NAME, "échec", f"tâche #{task.task_id} en échec ({exc}) → {r.code}", ok=False, code=r.code)
                continue
            finally:
                self.trace.ctx = {}
            self.db.complete_task(task.task_id, result)
            done += 1
        return done

    def process_reply(self, lead: Lead, text: str) -> str:
        self.trace.ctx = {"lead": lead.id}
        return self.setter.handle_reply(lead, text)

    def try_followup(self, lead: Lead, version_key: str) -> object:
        """Relance J3 : doit etre bloquee si une opposition existe."""
        self.trace.ctx = {"lead": lead.id}
        self.trace.emit(self.NAME, "Rédacteur", "tâche", f"relance J3 pour {lead.company}")
        res = self.db.create_message(f"relance:{lead.id}:{version_key}", "email", lead.email, "Relance", "Je me permets de relancer. Répondez STOP pour ne plus être contacté.", 0, "relance J3")
        self.trace.emit("Rédacteur", self.NAME, "résultat", f"relance : {res.code}", ok=res.ok, code=res.code)
        return res

    def evolution_proposals(self) -> list[dict]:
        """Boucle d'evolution : Hermes PROPOSE, il ne deploie rien sans l'approbation du fondateur."""
        props = []
        promo = [r for r in self.rejections if any("promesse" in i for i in r["issues"])]
        if promo:
            props.append({
                "id": "EVO-001", "statut": "proposition — en attente d'approbation du fondateur (rien n'est déployé)",
                "cause": f"{len(promo)} brouillon(s) rejeté(s) pour promesse chiffrée non démontrée",
                "preuve": [f"lead {r['lead']} v{r['version']}: {'; '.join(r['issues'])}" for r in promo],
                "version_actuelle": "prompt Rédacteur v1", "version_proposee": "prompt Rédacteur v2 : « n'écris jamais de pourcentage de gain »",
                "test": "10 brouillons en parallèle ancienne/nouvelle version, relus par le Censeur",
                "seuil_reussite": "0 promesse détectée sur 10 ; taux de rejet inférieur à l'ancien", "retour_arriere": "conserver v1 versionnée"})
        inj = [o for o in self.outcomes if o.get("flags") and o["status"] == "refusé_par_le_fondateur"]
        if inj:
            props.append({
                "id": "EVO-002", "statut": "proposition — en attente d'approbation du fondateur (rien n'est déployé)",
                "cause": "source contenant des consignes cachées : lead refusé après lecture",
                "preuve": [o["company"] for o in inj], "version_actuelle": "filtre d'injection v1",
                "version_proposee": "ajouter un marquage « source suspecte » dans le score de lead",
                "test": "rejouer les 20 dernières sources sur l'ancien et le nouveau filtre",
                "seuil_reussite": "même détection, 0 faux positif sur 20 sources saines", "retour_arriere": "conserver v1"})
        return props
