"""Simulation rapide : 3 leads (dont un High-Ticket) pour prouver les 4 corrections dans UNE exécution.

Réel : base PostgreSQL 16 temporaire, rôles et droits, budget et réserve, revue, approbation liée au hash, audit, déploiement de prompt.
Simulé : modèles (règles fixes, cloud facturé à coût fixe), SMTP (puits en mémoire), lien de paiement (factice, domaine .invalid),
décisions du fondateur (scriptées), leads (fictifs). Aucun réseau, aucune dépense, aucun e-mail.

    python -m nexus_agents.scenarios.simulation_rapide --log nexus_agents/preuves/simulation_rapide.log
"""
from __future__ import annotations

import argparse
from pathlib import Path

from nexus_core import Client
from nexus_core.tempdb import TempCluster

from ..agents import Analyste, Censeur, FondateurSimule, Redacteur, SimulatedSMTP, Setter, Sourcing, Transport
from ..closing import Closing, StubPaymentProvider
from ..gateway import ModelGateway
from ..hermes import CircuitBreaker, Hermes
from ..models import ModelOutput, StubCloudModel, StubLocalModel
from ..prompts import PromptStore, seed_defaults
from ..trace import Trace, TracedClient

CLOUD_COST = {"final_check": 150, "closing": 150}      # centimes par appel, coût fixe simulé


class FixedCostCloud(StubCloudModel):
    """Même verdict que le cloud simulé, mais facturé à coût fixe pour rendre la démonstration lisible."""
    def generate(self, task, payload, system_prompt=None):
        o = super().generate(task, payload, system_prompt)
        return ModelOutput(o.value, o.tokens_in, o.tokens_out, CLOUD_COST.get(task, 150), o.model, o.simulated)


LEADS = {
    "C": dict(id="C", company="Garage Perrin (fictif)", contact_name="Paul Perrin", email="contact@garage-perrin.example",
              source_url="", excerpt="Garage indépendant. Nous aimerions mieux suivre nos devis."),
    "B": dict(id="B", company="Menuiserie Roche (fictive)", contact_name="Anne Roche", email="anne.roche@menuiserie-roche.example",
              source_url="https://menuiserie-roche.example/atelier",
              excerpt="Menuiserie sur mesure. Les relances de factures impayées prennent trois heures par semaine. Atelier à Nantes."),
    "A": dict(id="A", company="Agence Lumière (fictive)", contact_name="Claire Martin", email="claire.martin@agence-lumiere.example",
              source_url="https://agence-lumiere.example/blog/devis",
              excerpt="Nous accompagnons des PME depuis 2014. Chaque semaine, notre équipe ressaisit à la main les devis et les factures dans un tableur."),
}


def run(log_path: str | None = None, echo: bool = True) -> dict:
    cluster = TempCluster(54353).start()
    db = cluster.new_database()
    lines: list = []
    checks: list = []
    try:
        adm = cluster.connect(db, "postgres")

        def clock(iso):
            adm.execute("DELETE FROM nexus.clock_override"); adm.execute("INSERT INTO nexus.clock_override VALUES (%s::timestamptz)", (iso,))

        def say(msg=""):
            lines.append(msg)
            if echo:
                print(msg)

        def check(num, label, ok, detail):
            checks.append({"correction": num, "label": label, "ok": bool(ok), "detail": detail})
            say(f"   {'✔' if ok else '✘'} [{num}] {label} — {detail}")

        clock("2026-10-05T10:00:00Z")
        # plafond quotidien volontairement bas (1,50 €) : un seul appel cloud le remplit ; réserve prioritaire 5,00 €
        adm.execute("UPDATE nexus.policy SET daily_api_cap_cents = 150, priority_reserve_daily_cents = 500, priority_min_score = 4")
        trace = Trace()
        mk = lambda role: Client.connect(**cluster.conninfo(db, f"nexus_{role}"))
        w, c, f, t = (mk(r) for r in ("worker", "censor", "founder", "transport"))
        tc = lambda cl, actor, role: TracedClient(cl, trace, actor, f"nexus_{role}")
        seed_defaults(adm)
        prompts = PromptStore(w)
        gw = ModelGateway(tc(w, "Passerelle de modèles", "worker"), trace, StubLocalModel(), FixedCostCloud(), prompts=prompts)
        sink = SimulatedSMTP()
        db_h = tc(w, "Hermes", "worker")
        fondateur = FondateurSimule(tc(f, "Fondateur (simulé)", "founder"), trace, {"B": "approve", "A": "approve", "A:closing": "approve"})
        hermes = Hermes(gateway=gw, db=db_h, trace=trace, sourcing=Sourcing(gw, trace, tc(w, "Sourcing", "worker")),
                        analyste=Analyste(gw, trace, tc(w, "Analyste", "worker")), redacteur=Redacteur(gw, tc(w, "Rédacteur", "worker"), trace),
                        censeur=Censeur(tc(c, "Censeur", "censor"), trace), fondateur=fondateur,
                        transport=Transport(tc(t, "Transport", "transport"), trace, sink),
                        setter=Setter(gw, tc(w, "Setter", "worker"), trace),
                        closing=Closing(gw, tc(w, "Closing", "worker"), trace, StubPaymentProvider(), clock=lambda: "2026-10-06"),
                        breaker=CircuitBreaker())

        def snap():
            s = w.budget_status()
            return (f"jour {s['daily_api']['committed'] / 100:.2f}/{s['daily_api']['cap'] / 100:.2f} € · "
                    f"réserve {s['priority_reserve']['committed'] / 100:.2f}/{s['priority_reserve']['cap'] / 100:.2f} € · "
                    f"mois {s['operating']['committed'] / 100:.2f}/{s['operating']['cap'] / 100:.2f} €")

        say("# Simulation rapide — 3 leads fictifs, base PostgreSQL réelle, modèles / SMTP / paiement / fondateur SIMULÉS")
        say("# Politique : plafond quotidien API 1,50 € · réserve prioritaire 5,00 € · score minimum 4/5 · tâches éligibles final_check, closing")
        say("# Leads : C « Garage Perrin » (sans source) · B « Menuiserie Roche » (standard, modèle faible) · A « Agence Lumière » (High-Ticket)")
        say()

        # ------------------------------------------------------------------ jour 1 : C et B
        say("== Jour 1 — C (sans source) et B (brouillon fautif, modèle faible)")
        clock("2026-10-05T10:05:00Z")
        hermes.enqueue_lead(LEADS["C"])
        hermes.enqueue_lead(LEADS["B"], model_quality="weak", cloud_check=True)
        hermes.run_pending()
        out = {o["lead"]: o for o in hermes.outcomes}
        rej = f.list_rejections()
        c_rej = [r for r in rej if r["lead"] == "C"]
        b_rev = [r for r in rej if r["lead"] == "B"]
        say(f"   issues : C → {out['C']['status']} · B → {out['B']['status']}   | {snap()}")
        check(1, "Observabilité : rejet du lead C détaillé en base",
              bool(c_rej) and all(c_rej[0].get(k) not in (None, "") for k in ("motif_exact", "preuve_source", "indice_confiance")),
              f"motif « {c_rej[0]['motif_exact'][:70]} » · preuve {c_rej[0]['preuve_source']} · confiance {c_rej[0]['indice_confiance']}" if c_rej else "aucun rejet enregistré")
        check(1, "Observabilité : rejet du brouillon de B par le Censeur détaillé",
              bool(b_rev) and "promesse" in b_rev[0]["motif_exact"].lower(),
              f"motif « {b_rev[0]['motif_exact'][:80]} » · confiance {b_rev[0]['indice_confiance']}" if b_rev else "aucun rejet")
        say()

        # ------------------------------------------------------------------ évolution
        say("== Jour 2, matin — boucle d'évolution : Hermes propose, le fondateur (simulé) approuve, déploiement sans redémarrage")
        clock("2026-10-06T08:00:00Z")
        v_before = prompts.active("Rédacteur").version
        ids = hermes.submit_evolutions(prompts)
        if ids:
            fondateur.decide_evolution(ids[0], "APPROUVÉ")
        v_after = prompts.active("Rédacteur").version
        log = f.deployment_log()
        msg = log[-1]["message"] if log else ""
        check(3, "Évolution : prompt Rédacteur déployé automatiquement à l'approbation",
              v_after == v_before + 1 and msg == f"Prompt Agent Rédacteur mis à jour vers Version {v_after}",
              f"v{v_before} → v{v_after} · journal : « {msg} » · aucun redémarrage (lecture en base à chaque appel)")
        say()

        # ------------------------------------------------------------------ jour 2 : A High-Ticket
        say("== Jour 2 — A (High-Ticket) : le plafond du jour est d'abord rempli par un appel ordinaire (lead de score 3)")
        clock("2026-10-06T08:30:00Z")
        def prio(lead, task=None):      # appels réellement accordés via la réserve, lus dans le journal d'audit de la base
            return adm.execute("""SELECT count(*) FROM nexus.audit_log WHERE event = 'budget_reserved' AND payload->>'priority_reserve' = 'true'
                                    AND payload->>'lead' = %s AND (%s::text IS NULL OR payload->>'task' = %s)""", (lead, task, task)).fetchone()[0]

        w.record_lead_score("OUVERTURE-J2", 3, "scénario : lead ordinaire")
        r0 = gw.run("final_check", {"body": "texte ordinaire"}, caller="Hermes", allow_cloud=True, est_cents=150,
                    idem="ouverture-j2", lead_ref="OUVERTURE-J2")
        say(f"   appel ordinaire (score 3) : {'accepté' if r0.ok else 'refusé ' + r0.code}   | {snap()}")
        hermes.enqueue_lead(LEADS["A"], model_quality="weak", cloud_check=True)
        mark = len(trace.events)
        hermes.run_pending()
        oa = [o for o in hermes.outcomes if o["lead"] == "A"][-1]
        n_fc = prio("A", "final_check")
        a_rej = [r for r in f.list_rejections() if r["lead"] == "A" and "promesse" in r["motif_exact"].lower()]
        say(f"   issue A → {oa['status']} (version {oa.get('version')})   | {snap()}")
        check(3, "Évolution : le prompt v2 supprime la promesse dès le 1er jet de A (modèle faible inchangé)",
              oa.get("version") == 1 and not a_rej and oa["status"] in ("sent", "approved"),
              f"A envoyé en version {oa.get('version')}, aucun rejet « promesse » (B avait besoin de 2 versions)")
        check(4, "Réserve prioritaire : le contrôle cloud de A passe le plafond quotidien",
              n_fc >= 1, f"{n_fc} appel(s) final_check accordé(s) via la réserve (audit base) · {snap()}")
        say()

        say("== Jour 2 — A répond « prêt à signer » : closing automatique")
        clock("2026-10-06T09:00:00Z")
        n_sent_before = len(sink.sent)
        hermes.enqueue_reply(LEADS["A"], "D'accord pour l'audit de 4 h à 490 €, envoyez-moi le devis.")
        mark = len(trace.events)
        hermes.run_pending()
        cl = hermes.closings[-1] if hermes.closings else {}
        docs = f.list_documents()
        d = docs[-1] if docs else {}
        v = d.get("variables", {})
        sent_pre = len(sink.sent) - n_sent_before
        n_cl = prio("A", "closing")
        notif = [n["kind"] for n in f.notifications()]
        check(2, "Closing : variables extraites (Nom, Entreprise, Prix, Périmètre)",
              all(v.get(k) for k in ("nom", "entreprise", "prix_eur_ht", "perimetre")),
              f"nom={v.get('nom')} · entreprise={v.get('entreprise')} · prix={v.get('prix_eur_ht')} € HT · périmètre={str(v.get('perimetre'))[:48]}…")
        check(2, "Closing : PDF généré et empreinte calculée par la base",
              bool(d) and d.get("bytes", 0) > 500 and len(d.get("sha256", "")) == 64,
              f"{d.get('bytes')} octets · sha256 {d.get('sha256', '')[:16]}… · modèle {d.get('template')}")
        check(2, "Closing : lien de paiement SIMULÉ joint et dépôt en file d'approbation (rien d'envoyé)",
              cl.get("ok") and cl.get("link_simulated") and "document_ready" in notif and sent_pre == 0,
              f"fournisseur {cl.get('link_provider')} (simulé) · notification document_ready · messages envoyés avant validation : {sent_pre}")
        check(4, "Réserve prioritaire : le contrôle « closing » passe aussi le plafond quotidien",
              n_cl >= 1, f"{n_cl} appel(s) closing accordé(s) via la réserve (audit base) · {snap()}")

        clock("2026-10-06T09:20:00Z")
        hermes.decide_pending_closings()
        pdf_sent = [m for m in sink.sent if str(m.get("attachments", "[]")) not in ("[]", "", "None")]
        check(2, "Closing : après validation (simulée) du fondateur, le devis part avec son PDF",
              len(pdf_sent) >= 1, f"{len(pdf_sent)} message(s) avec pièce jointe remis au puits SMTP simulé")
        say()

        # ------------------------------------------------------------------ sonde : refus hors éligibilité
        say("== Sonde (lead FICTIF de score 3, étiqueté) : la réserve n'est pas ouverte hors éligibilité")
        w.record_lead_score("SONDE-3", 3, "scénario : sonde")
        rp = gw.run("final_check", {"body": "texte"}, caller="Hermes", allow_cloud=True, est_cents=150, idem="sonde-1", lead_ref="SONDE-3")
        rq = gw.run("deep_check", {"body": "texte"}, caller="Hermes", allow_cloud=True, est_cents=150, idem="sonde-2", lead_ref="A", category="research")
        say(f"   score 3 / final_check → {'accepté' if rp.ok else 'REFUSÉ (' + rp.code + ')'} · score 5 / deep_check → {'accepté' if rq.ok else 'REFUSÉ (' + rq.code + ')'}")
        check(4, "Réserve bornée par l'éligibilité décidée en base (score ≥ 4 ET tâche final_check/closing)",
              (not rp.ok) and (not rq.ok), f"score 3 : {rp.code} · deep_check : {rq.code}")
        say()

        chain = w.verify_audit()
        s = w.budget_status()
        check(0, "Chaîne d'audit intacte et enveloppe mensuelle respectée",
              chain is None and s["operating"]["committed"] <= s["operating"]["cap"],
              f"audit {'intact' if chain is None else 'ROMPU à ' + str(chain)} · mois {s['operating']['committed'] / 100:.2f}/{s['operating']['cap'] / 100:.2f} €")
        ok_all = all(x["ok"] for x in checks)
        say()
        say(f"== Bilan : {sum(x['ok'] for x in checks)}/{len(checks)} contrôles réussis — {'LES 4 CORRECTIONS FONCTIONNENT dans ce scénario' if ok_all else 'ÉCHEC'}")
        say("-- Limites : modèles, SMTP, lien de paiement et décisions du fondateur sont simulés ; trois leads fictifs ne prouvent ni le taux de conversion,")
        say("   ni la qualité de vrais modèles. Cette exécution prouve la mécanique (traçabilité, droits, budget, déploiement), pas un résultat commercial.")
        report = {"checks": checks, "ok": ok_all, "lines": lines, "audit_chain": chain}
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(log_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report
    finally:
        cluster.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="nexus_agents/preuves/simulation_rapide.log")
    a = ap.parse_args()
    r = run(a.log)
    raise SystemExit(0 if r["ok"] else 1)
