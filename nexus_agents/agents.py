"""Agents specialises. Chacun a un role de base de donnees, des droits limites et parle par la trace."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .gateway import ModelGateway
from .models import OPT_OUT_RX
from .trace import Trace

FREE_MAIL = {"gmail.com", "yahoo.fr", "yahoo.com", "hotmail.com", "hotmail.fr", "outlook.com", "orange.fr", "free.fr"}
SENTINEL = "Client qualifié et prêt à signer. Validation manuelle requise pour l'envoi du contrat."
EURO_PER_HOUR = 25   # valeur horaire H du plan A-Z : hypothese, pas une mesure
SENDER = "Nexus"


@dataclass
class Lead:
    id: str
    company: str
    contact_name: str
    email: str
    source_url: str
    excerpt: str
    score: int = 0
    flags: list = field(default_factory=list)

    @property
    def domain(self) -> str:
        return self.email.rsplit("@", 1)[-1].lower()


@dataclass
class Analysis:
    quote: str
    topic: str
    hours_low: float
    hours_high: float
    euro_low: int
    euro_high: int
    assumptions: str


class Sourcing:
    NAME = "Sourcing"

    def __init__(self, gateway: ModelGateway, trace: Trace):
        self.gw, self.trace = gateway, trace
        self.seen: dict = {}     # domaine -> id du lead qui l'a pris en premier

    def validate(self, raw: dict) -> tuple[Optional[Lead], str]:
        t = self.trace
        t.emit("Hermes", self.NAME, "tâche", f"valider le lead {raw.get('id')} ({raw.get('company')})")
        url, email = raw.get("source_url") or "", (raw.get("email") or "").strip().lower()
        if not url.startswith("https://"):
            t.emit(self.NAME, "Hermes", "rejet", "pas de source publique vérifiable → pas de fait validé", ok=False, code="no_source")
            return None, "no_source"
        if "@" not in email or email.rsplit("@", 1)[-1] in FREE_MAIL:
            t.emit(self.NAME, "Hermes", "rejet", "adresse non professionnelle", ok=False, code="not_pro_email")
            return None, "not_pro_email"
        domain = email.rsplit("@", 1)[-1]
        if self.seen.get(domain, raw.get("id")) != raw.get("id"):      # un meme lead relance apres incident n'est pas un doublon
            t.emit(self.NAME, "Hermes", "rejet", f"doublon (domaine {domain} déjà traité)", ok=False, code="duplicate")
            return None, "duplicate"
        r = self.gw.run("score_lead", {"source_url": url, "email_pro": True, "excerpt": raw.get("excerpt", ""),
                                       "contact_name": raw.get("contact_name")},
                        caller=self.NAME, external_keys=("excerpt",))
        score = r.output["score"] if r.ok else 0
        if score < 3:
            t.emit(self.NAME, "Hermes", "rejet", f"score {score}/5 < 3", ok=False, code="low_score")
            return None, "low_score"
        self.seen[domain] = raw.get("id")
        lead = Lead(raw["id"], raw["company"], raw.get("contact_name", ""), email, url, raw.get("excerpt", ""), score,
                    [f["rule"] for f in r.injections])
        t.emit(self.NAME, "Hermes", "livrable", f"lead retenu, score {score}/5", ok=True, code="ok", score=score,
               source_url=url, flags=lead.flags)
        return lead, "ok"


class Analyste:
    NAME = "Analyste"

    def __init__(self, gateway: ModelGateway, trace: Trace):
        self.gw, self.trace = gateway, trace

    def analyse(self, lead: Lead) -> Optional[Analysis]:
        t = self.trace
        t.emit("Hermes", self.NAME, "tâche", f"extraire un fait vérifiable pour {lead.company}")
        r = self.gw.run("extract_fact", {"excerpt": lead.excerpt}, caller=self.NAME, external_keys=("excerpt",))
        quote = (r.output or {}).get("quote") if r.ok else None
        # controle deterministe : la citation doit exister MOT POUR MOT dans la page source
        if not quote or quote not in lead.excerpt:
            t.emit(self.NAME, "Hermes", "rejet", "citation introuvable mot pour mot dans la source → lead écarté",
                   ok=False, code="no_verifiable_fact")
            return None
        topic = r.output["topic"]
        from .models import HOURS_BY_TOPIC
        h = HOURS_BY_TOPIC.get(topic, 4)
        a = Analysis(quote, topic, round(h * 0.7, 1), round(h * 1.3, 1), int(h * 0.7 * EURO_PER_HOUR), int(h * 1.3 * EURO_PER_HOUR),
                     f"ESTIMATION : {h} h/mois de travail manuel sur « {topic} » ±30 %, valorisé {EURO_PER_HOUR} €/h (hypothèse, non mesurée).")
        t.emit(self.NAME, "Hermes", "livrable", f"fait vérifié + estimation {a.euro_low}–{a.euro_high} €/mois (hypothèse)",
               ok=True, code="ok", quote=quote, assumptions=a.assumptions)
        return a


class Redacteur:
    NAME = "Rédacteur"

    def __init__(self, gateway: ModelGateway, db, trace: Trace):
        self.gw, self.db, self.trace = gateway, db, trace

    def draft(self, lead: Lead, a: Analysis, model_quality="normal"):
        t = self.trace
        t.emit("Hermes", self.NAME, "tâche", f"rédiger le premier message pour {lead.company}")
        r = self.gw.run("draft_message", {"company": lead.company, "contact_name": lead.contact_name, "fact_quote": a.quote,
                                          "sender": SENDER, "model_quality": model_quality},
                        caller=self.NAME, external_keys=("fact_quote",))
        if not r.ok:
            return None
        res = self.db.create_message(f"draft:{lead.id}:v1", "email", lead.email, r.output["subject"], r.output["body"], 0,
                                     "pilote P1 audit de processus")
        t.emit(self.NAME, "Hermes", "livrable" if res.ok else "rejet", f"brouillon déposé ({res.code})", ok=res.ok, code=res.code,
               message_id=res.id)
        return res

    def revise(self, prev_id: int, version: int, msg: dict, issues: list):
        t = self.trace
        t.emit("Censeur", self.NAME, "retour", f"rejet de la v{version} : {'; '.join(issues)[:120]}", ok=False, code="rejected")
        r = self.gw.run("revise_message", {"subject": msg["subject"], "body": msg["body"], "issues": issues}, caller=self.NAME)
        res = self.db.create_revision(prev_id, f"revise:{prev_id}", r.output["subject"], r.output["body"], 0, msg["purpose"])
        t.emit(self.NAME, "Hermes", "livrable" if res.ok else "rejet", f"v{version + 1} déposée ({res.code})", ok=res.ok, code=res.code,
               message_id=res.id)
        return res


class Censeur:
    """Revue independante : un autre role de base, qui ne peut ni rediger ni approuver."""
    NAME = "Censeur"

    def __init__(self, db, trace: Trace):
        self.db, self.trace = db, trace

    @staticmethod
    def check(subject: str, body: str) -> tuple[dict, list]:
        issues = []
        d = {"orthographe": True, "ton": True, "promesses_preuves": True, "repetitions": True}
        if re.search(r" {2,}| ,|\.\.\.\.", body):
            d["orthographe"] = False; issues.append("espaces ou ponctuation anormaux")
        if body.count("!") > 1 or len(re.findall(r"\b[A-ZÀ-Ý]{5,}\b", body.replace("STOP", ""))) > 1:
            d["ton"] = False; issues.append("ton trop insistant (points d'exclamation / majuscules)")
        from .models import RISKY
        if any(re.search(rx, body, re.I) for rx in RISKY):
            d["promesses_preuves"] = False; issues.append("promesse de résultat chiffrée non démontrée")
        words = [w for w in re.findall(r"\w{5,}", body.lower())]
        if any(words.count(w) >= 4 for w in set(words)):
            d["repetitions"] = False; issues.append("répétitions")
        if "STOP" not in body:
            d["promesses_preuves"] = False; issues.append("phrase de désinscription absente")
        return d, issues

    def review(self, message_id: int):
        t = self.trace
        t.emit("Hermes", self.NAME, "tâche", f"relire le message #{message_id} (sans l'avoir écrit)")
        msg = self.db.get_message(message_id)
        dims, issues = self.check(msg["subject"], msg["body"])
        verdict = "pass" if all(dims.values()) else "reject"
        res = self.db.review(message_id, verdict, dims, None if verdict == "pass" else "; ".join(issues))
        t.emit(self.NAME, "Hermes", "verdict", f"{verdict} — {dims}", ok=res.ok and verdict == "pass", code=res.code, dimensions=dims)
        return verdict, issues, msg


class FondateurSimule:
    """DEMONSTRATION : decisions humaines scriptees. En production, c'est vous, sur l'interface."""
    NAME = "Fondateur (simulé)"

    def __init__(self, db, trace: Trace, script: dict):
        self.db, self.trace, self.script = db, trace, script

    def decide(self, lead: Lead, message_id: int, hours=24):
        t = self.trace
        decision = self.script.get(lead.id, "reject")
        msg = self.db.get_message(message_id)
        t.emit("Hermes", self.NAME, "demande", f"approbation du texte exact #{message_id} (hash {msg['content_hash'][:10]}…)",
               flags=lead.flags)
        if decision == "approve":
            res = self.db.approve(message_id, msg["content_hash"], hours)
            t.emit(self.NAME, "Noyau Nexus", "décision", "APPROUVÉ (décision humaine simulée)", ok=res.ok, code=res.code)
            return res.ok
        res = self.db.founder_reject(message_id, "refusé après lecture (démonstration)")
        t.emit(self.NAME, "Noyau Nexus", "décision", "REFUSÉ (décision humaine simulée)", ok=False, code=res.code)
        return False


class SimulatedSMTP:
    """Puits en memoire : AUCUN reseau, aucun e-mail reel."""
    def __init__(self):
        self.sent: list = []


class Transport:
    NAME = "Transport"

    def __init__(self, db, trace: Trace, sink: SimulatedSMTP, crash_after_claim: int = 0):
        self.db, self.trace, self.sink = db, trace, sink
        self.crash_after_claim = crash_after_claim      # DEMONSTRATION : simule un plantage apres la reservation d'envoi

    def drain(self):
        n = 0
        while True:
            self.trace.emit("Hermes", self.NAME, "tâche", "prendre le prochain message approuvé")
            row = self.db.claim()
            if row is None:
                break
            if self.crash_after_claim > 0:
                self.crash_after_claim -= 1
                self.trace.emit(self.NAME, self.NAME, "plantage", "panne simulée APRÈS la réservation d'envoi : le bail reste posé", ok=False, code="crash")
                raise RuntimeError("panne simulée du transport")
            pre = self.db.precheck(row.message_id)
            if not pre.ok:
                self.trace.emit(self.NAME, "Hermes", "blocage", f"contrôle final : {pre.code}", ok=False, code=pre.code)
                continue
            self.sink.sent.append({"message_id": row.message_id, "to": row.recipient, "subject": row.subject, "body": row.body})
            ref = f"sink-{len(self.sink.sent)}"
            res = self.db.mark_sent(row.message_id, ref, 0)
            self.trace.emit(self.NAME, "SMTP simulé", "envoi", f"« remis » au puits en mémoire (aucun réseau) → {row.recipient}",
                            ok=res.ok, code=res.code, provider_ref=ref)
            n += 1
        return n


class Setter:
    NAME = "Setter"

    def __init__(self, gateway: ModelGateway, db, trace: Trace):
        self.gw, self.db, self.trace = gateway, db, trace

    def handle_reply(self, lead: Lead, text: str):
        t = self.trace
        t.emit("Hermes", self.NAME, "tâche", f"traiter la réponse de {lead.company}", reply=text[:140])
        r = self.gw.run("classify_reply", {"text": text}, caller=self.NAME, external_keys=("text",))
        label = r.output["label"] if r.ok else "neutral"
        if label != "opt_out" and OPT_OUT_RX.search(text):
            # filet deterministe : une opposition est honoree meme si le modele l'a mal classee
            t.emit(self.NAME, self.NAME, "filet", f"opposition détectée par règle fixe (le modèle avait dit « {label} »)", ok=True, code="opt_out_guard")
            label = "opt_out"
        if r.injections:
            self.db.notify_founder("injection_attempt", f"{lead.id}:reply",
                                   f"Réponse de {lead.company} contenant une consigne ignorée : {r.injections[0]['sentence'][:200]}")
        if label == "opt_out":
            self.db.suppress(lead.email, "opposition reçue par réponse")
            t.emit(self.NAME, "Hermes", "décision", "opposition → suppression immédiate, plus aucune relance", ok=True, code="opt_out")
        elif label == "hostile":
            self.db.suppress(lead.email, "réponse hostile")
            self.db.notify_founder("hostile_reply", lead.id, f"Réponse hostile de {lead.company} : {text[:300]}")
            t.emit(self.NAME, "Hermes", "décision", "réponse hostile → suppression + alerte fondateur, aucune réponse automatique", ok=True, code="hostile")
        elif label == "agreement":
            self.db.notify_founder("ready_to_sign", lead.id, f"{SENTINEL} Lead : {lead.company}. Périmètre et prix évoqués par le prospect : « {text[:200]} »")
            t.emit(self.NAME, "Fondateur (simulé)", "notification", SENTINEL, ok=True, code="ready_to_sign")
        elif label == "positive":
            self.db.notify_founder("needs_human", lead.id, f"Réponse positive de {lead.company} : {text[:300]}. À qualifier (périmètre, prix) avant tout devis.")
            t.emit(self.NAME, "Fondateur (simulé)", "notification", "réponse positive → à qualifier par un humain (pas encore prêt à signer)", ok=True, code="needs_human")
        else:
            t.emit(self.NAME, "Hermes", "décision", "réponse neutre → aucune action automatique", ok=True, code="neutral")
        return label
