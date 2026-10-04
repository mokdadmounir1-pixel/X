"""Agents specialises. Chacun a un role de base de donnees, des droits limites et parle par la trace.

Tout ecartement produit un `RejectionDetail` (motif exact, preuve, indice de confiance), ecrit en base et affiche au journal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import rejection as rj
from .gateway import ModelGateway
from .models import HOURS_BY_TOPIC, OPT_OUT_RX, RISKY
from .trace import Trace

FREE_MAIL = {"gmail.com", "yahoo.fr", "yahoo.com", "hotmail.com", "hotmail.fr", "outlook.com", "orange.fr", "free.fr"}
SENTINEL = "Client qualifié et prêt à signer. Validation manuelle requise pour l'envoi du contrat."
EURO_PER_HOUR = 25   # valeur horaire H du plan A-Z : hypothese, pas une mesure
SENDER = "Nexus"
MIN_SCORE = 3


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

    def __init__(self, gateway: ModelGateway, trace: Trace, db):
        self.gw, self.trace, self.db = gateway, trace, db
        self.seen: dict = {}     # domaine -> id du lead qui l'a pris en premier

    def _reject(self, raw, d: rj.RejectionDetail):
        rj.emit_rejection(self.trace, self.db, self.NAME, "Hermes", raw["id"], d)
        return None, d

    def validate(self, raw: dict) -> tuple[Optional[Lead], Optional[rj.RejectionDetail]]:
        t = self.trace
        t.emit("Hermes", self.NAME, "tâche", f"valider le lead {raw.get('id')} ({raw.get('company')})")
        url, email = raw.get("source_url") or "", (raw.get("email") or "").strip().lower()
        if not url.startswith("https://"):
            return self._reject(raw, rj.deterministic("sourcing", self.NAME,
                f"aucune URL source https fournie (champ source_url : « {url or 'vide'} »)",
                {"type": "champ_absent", "champ": "source_url", "valeur": url or None, "regle": "source publique https obligatoire"}))
        domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        if not domain or domain in FREE_MAIL:
            return self._reject(raw, rj.deterministic("sourcing", self.NAME,
                f"adresse non professionnelle ou invalide (domaine « {domain or 'absent'} » = messagerie grand public)",
                {"type": "regle", "regle": "FREE_MAIL", "domaine": domain or None, "source_url": url}))
        first = self.seen.get(domain)
        if first is not None and first != raw.get("id"):      # un meme lead relance apres incident n'est pas un doublon
            return self._reject(raw, rj.deterministic("sourcing", self.NAME,
                f"doublon : le domaine {domain} est déjà pris par le lead {first}",
                {"type": "registre", "domaine": domain, "lead_precedent": first}))
        r = self.gw.run("score_lead", {"source_url": url, "email_pro": True, "excerpt": raw.get("excerpt", ""),
                                       "contact_name": raw.get("contact_name")}, caller=self.NAME, external_keys=("excerpt",), lead_ref=raw["id"])
        score = r.output["score"] if r.ok else 0
        comp = {"source": 1 if url else 0, "email_pro": 1, "signal_achat": 2 if any(k in (raw.get("excerpt") or "").lower() for k in
                ("facture", "devis", "paiement", "relance", "retard", "tableur", "export", "saisie")) else 0,
                "contact_nomme": 1 if raw.get("contact_name") else 0}
        # le score est ecrit UNE fois en base : c'est lui, et pas l'appelant, qui ouvre ou non la reserve prioritaire
        self.db.record_lead_score(raw["id"], score, "regles: " + ", ".join(f"{k}={v}" for k, v in comp.items()))
        if score < MIN_SCORE:
            return self._reject(raw, rj.heuristic("sourcing", self.NAME,
                f"score {score}/5 inférieur au minimum {MIN_SCORE} (composantes : {comp})",
                {"type": "score", "score": score, "seuil": MIN_SCORE, "composantes": comp, "source_url": url},
                0.5 + 0.1 * (MIN_SCORE - score)))
        self.seen[domain] = raw.get("id")
        lead = Lead(raw["id"], raw["company"], raw.get("contact_name", ""), email, url, raw.get("excerpt", ""), score,
                    [f["rule"] for f in r.injections])
        t.emit(self.NAME, "Hermes", "livrable", f"lead retenu, score {score}/5", ok=True, code="ok", score=score, source_url=url, flags=lead.flags)
        return lead, None


class Analyste:
    NAME = "Analyste"

    def __init__(self, gateway: ModelGateway, trace: Trace, db):
        self.gw, self.trace, self.db = gateway, trace, db

    def analyse(self, lead: Lead) -> tuple[Optional[Analysis], Optional[rj.RejectionDetail]]:
        t = self.trace
        t.emit("Hermes", self.NAME, "tâche", f"extraire un fait vérifiable pour {lead.company}")
        r = self.gw.run("extract_fact", {"excerpt": lead.excerpt}, caller=self.NAME, external_keys=("excerpt",), lead_ref=lead.id)
        if not r.ok:
            d = rj.deterministic("analyse", self.NAME, f"le modèle n'a pas pu analyser la source ({r.code})",
                                 {"type": "erreur_modele", "code": r.code, "source_url": lead.source_url})
            rj.emit_rejection(t, self.db, self.NAME, "Hermes", lead.id, d)
            return None, d
        quote = (r.output or {}).get("quote")
        # controle deterministe : la citation doit exister MOT POUR MOT dans la page source
        if quote and quote not in lead.excerpt:
            d = rj.deterministic("analyse", self.NAME, "la citation proposée par le modèle est absente de la source mot pour mot (invention probable)",
                                 {"type": "source", "url": lead.source_url, "citation_proposee": quote[:200], "extrait_source": lead.excerpt[:200]})
        elif not quote:
            d = rj.heuristic("analyse", self.NAME, "aucune phrase de la source ne décrit un problème de facture, devis, relance ou export",
                             {"type": "source", "url": lead.source_url, "extrait_source": lead.excerpt[:200],
                              "mots_cles_cherches": ["facture", "devis", "paiement", "relance", "retard", "tableur", "export", "saisie"]}, 0.8)
        else:
            d = None
        if d:
            rj.emit_rejection(t, self.db, self.NAME, "Hermes", lead.id, d)
            return None, d
        topic = r.output["topic"]
        h = HOURS_BY_TOPIC.get(topic, 4)
        a = Analysis(quote, topic, round(h * 0.7, 1), round(h * 1.3, 1), int(h * 0.7 * EURO_PER_HOUR), int(h * 1.3 * EURO_PER_HOUR),
                     f"ESTIMATION : {h} h/mois de travail manuel sur « {topic} » ±30 %, valorisé {EURO_PER_HOUR} €/h (hypothèse, non mesurée).")
        t.emit(self.NAME, "Hermes", "livrable", f"fait vérifié + estimation {a.euro_low}–{a.euro_high} €/mois (hypothèse)",
               ok=True, code="ok", quote=quote, assumptions=a.assumptions)
        return a, None


class Redacteur:
    NAME = "Rédacteur"

    def __init__(self, gateway: ModelGateway, db, trace: Trace):
        self.gw, self.db, self.trace = gateway, db, trace

    def _db_refusal(self, lead: Lead, code: str) -> rj.RejectionDetail:
        """Traduit un refus de la base en motif exact, avec la preuve (jamais l'adresse en clair)."""
        if code == "suppressed":
            info = self.db.suppression_info(lead.email) or {}
            when = str(info.get("added_at", "date inconnue"))[:10]
            return rj.deterministic("redaction", self.NAME,
                f"opposition enregistrée le {when} (motif de l'opposition : {info.get('reason', 'non précisé')})",
                {"type": "suppression", "recipient_sha256": info.get("recipient_sha256"), "raison": info.get("reason"), "date": when,
                 "table": "suppression"})
        motifs = {"bad_recipient": "adresse du destinataire invalide pour un envoi e-mail",
                  "idem_conflict": "un brouillon différent existe déjà pour ce lead (clé d'idempotence en conflit)",
                  "bad_input": "brouillon incomplet refusé par la base (champ obligatoire manquant)"}
        return rj.deterministic("redaction", self.NAME, motifs.get(code, f"brouillon refusé par la base ({code})"),
                                {"type": "validation_base", "code": code, "lead": lead.id})

    def draft(self, lead: Lead, a: Analysis, model_quality="normal"):
        t = self.trace
        t.emit("Hermes", self.NAME, "tâche", f"rédiger le premier message pour {lead.company}")
        r = self.gw.run("draft_message", {"company": lead.company, "contact_name": lead.contact_name, "fact_quote": a.quote,
                                          "sender": SENDER, "model_quality": model_quality},
                        caller=self.NAME, external_keys=("fact_quote",), lead_ref=lead.id)
        if not r.ok:
            motif = {"model_not_qualified": "modèle local non qualifié pour la rédaction (banc de qualification) : tâche mise en pause",
                     "model_unavailable": "le modèle n'a pas répondu à la demande de rédaction"}.get(r.code, f"rédaction impossible ({r.code})")
            d = rj.deterministic("redaction", self.NAME, motif, {"type": "passerelle", "code": r.code, "tache": "draft_message"})
            rj.emit_rejection(t, self.db, self.NAME, "Hermes", lead.id, d)
            return None, d
        res = self.db.create_message(f"draft:{lead.id}:v1", "email", lead.email, r.output["subject"], r.output["body"], 0,
                                     "pilote P1 audit de processus")
        if not res.ok:
            d = self._db_refusal(lead, res.code)
            rj.emit_rejection(t, self.db, self.NAME, "Hermes", lead.id, d)
            return res, d
        t.emit(self.NAME, "Hermes", "livrable", f"brouillon déposé ({res.code})", ok=True, code=res.code, message_id=res.id)
        return res, None

    def revise(self, prev_id: int, version: int, msg: dict, issues: list):
        t = self.trace
        t.emit("Censeur", self.NAME, "retour", f"rejet de la v{version} : {'; '.join(issues)[:120]}", ok=False, code="rejected")
        r = self.gw.run("revise_message", {"subject": msg["subject"], "body": msg["body"], "issues": issues}, caller=self.NAME)
        res = self.db.create_revision(prev_id, f"revise:{prev_id}", r.output["subject"], r.output["body"], 0, msg["purpose"])
        t.emit(self.NAME, "Hermes", "livrable" if res.ok else "rejet", f"v{version + 1} déposée ({res.code})", ok=res.ok, code=res.code, message_id=res.id)
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
        if any(re.search(rx, body, re.I) for rx in RISKY):
            d["promesses_preuves"] = False; issues.append("promesse de résultat chiffrée non démontrée")
        words = [w for w in re.findall(r"\w{5,}", body.lower())]
        if any(words.count(w) >= 4 for w in set(words)):
            d["repetitions"] = False; issues.append("répétitions")
        if "STOP" not in body:
            d["promesses_preuves"] = False; issues.append("phrase de désinscription absente")
        return d, issues

    def review(self, message_id: int, lead_ref: str | None = None):
        t = self.trace
        t.emit("Hermes", self.NAME, "tâche", f"relire le message #{message_id} (sans l'avoir écrit)")
        msg = self.db.get_message(message_id)
        dims, issues = self.check(msg["subject"], msg["body"])
        verdict = "pass" if all(dims.values()) else "reject"
        res = self.db.review(message_id, verdict, dims, None if verdict == "pass" else "; ".join(issues))
        t.emit(self.NAME, "Hermes", "verdict", f"{verdict} — {dims}", ok=res.ok and verdict == "pass", code=res.code, dimensions=dims)
        if verdict == "reject" and lead_ref:
            d = rj.deterministic("revue", self.NAME, f"message #{message_id} v{msg['version']} rejeté par la revue : {'; '.join(issues)}",
                                 {"type": "revue", "message_id": message_id, "version": msg["version"], "dimensions": dims,
                                  "content_hash": msg["content_hash"]})
            rj.emit_rejection(t, self.db, self.NAME, "Rédacteur", lead_ref, d, kind="rejet_message")
        return verdict, issues, msg


class FondateurSimule:
    """DEMONSTRATION : decisions humaines scriptees. En production, c'est vous, sur l'interface."""
    NAME = "Fondateur (simulé)"

    def __init__(self, db, trace: Trace, script: dict):
        self.db, self.trace, self.script = db, trace, script

    def decide(self, lead: Lead, message_id: int, hours=24, key: str | None = None):
        t = self.trace
        decision = self.script.get(key or lead.id, "reject")
        msg = self.db.get_message(message_id)
        t.emit("Hermes", self.NAME, "demande", f"approbation du texte exact #{message_id} (hash {msg['content_hash'][:10]}…)", flags=lead.flags)
        if decision == "approve":
            res = self.db.approve(message_id, msg["content_hash"], hours)
            t.emit(self.NAME, "Noyau Nexus", "décision", "APPROUVÉ (décision humaine simulée)", ok=res.ok, code=res.code)
            return res.ok
        res = self.db.founder_reject(message_id, "refusé après lecture (démonstration)")
        t.emit(self.NAME, "Noyau Nexus", "décision", "REFUSÉ (décision humaine simulée)", ok=False, code=res.code)
        return False

    def decide_evolution(self, evolution_id: int, decision: str):
        res = self.db.decide_evolution(evolution_id, decision)
        self.trace.emit(self.NAME, "Noyau Nexus", "décision", f"évolution #{evolution_id} : {decision} (décision humaine simulée) → {res.code}",
                        ok=res.ok, code=res.code)
        return res


class SimulatedSMTP:
    """Puits en memoire : AUCUN reseau, aucun e-mail reel."""
    def __init__(self):
        self.sent: list = []


class Transport:
    NAME = "Transport"
    _SHA = re.compile(r"empreinte sha256 : ([0-9a-f]{64})")

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
            entry = {"message_id": row.message_id, "to": row.recipient, "subject": row.subject, "body": row.body, "attachments": []}
            m = self._SHA.search(row.body)
            if m:                                    # le devis PDF dont l'empreinte figure dans le texte approuve
                doc = self.db.get_document_by_sha(m.group(1))
                if doc:
                    entry["attachments"].append({"filename": f"devis-{doc.variables.get('entreprise', '')}.pdf", "sha256": doc.sha256,
                                                 "bytes": len(doc.pdf), "document_id": doc.id})
            self.sink.sent.append(entry)
            ref = f"sink-{len(self.sink.sent)}"
            res = self.db.mark_sent(row.message_id, ref, 0)
            self.trace.emit(self.NAME, "SMTP simulé", "envoi", f"« remis » au puits en mémoire (aucun réseau) → {row.recipient}"
                            + (f" + pièce jointe {entry['attachments'][0]['sha256'][:10]}…" if entry["attachments"] else ""),
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
        r = self.gw.run("classify_reply", {"text": text}, caller=self.NAME, external_keys=("text",), lead_ref=lead.id)
        label = r.output["label"] if r.ok else "neutral"
        if r.injections:
            self.db.notify_founder("injection_attempt", f"{lead.id}:reply",
                                   f"Réponse de {lead.company} contenant une consigne ignorée : {r.injections[0]['sentence'][:200]}")
        if label != "opt_out" and OPT_OUT_RX.search(text):
            # filet deterministe : une opposition est honoree meme si le modele l'a mal classee
            t.emit(self.NAME, self.NAME, "filet", f"opposition détectée par règle fixe (le modèle avait dit « {label} »)", ok=True, code="opt_out_guard")
            label = "opt_out"
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
