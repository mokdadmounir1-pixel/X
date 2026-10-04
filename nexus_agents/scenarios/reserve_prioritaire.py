"""Preuve : un lead High-Ticket (score >= 4) franchit le plafond QUOTIDIEN d'API grace a la reserve prioritaire.

Ce que le scenario prouve, et ce qu'il ne prouve pas :
- la base accorde la reserve d'apres le score ENREGISTRE du lead et la tache (final_check / closing), pas d'apres ce que l'appelant declare ;
- la reserve est BORNEE (plafond quotidien propre) et puise dans l'enveloppe MENSUELLE : elle ne cree pas d'argent ;
- elle ne garantit pas « zero perte » : un lead haut de gamme est refuse si la reserve du jour ou l'enveloppe du mois est epuisee.
Modele cloud SIMULE a cout fixe ; aucun reseau, aucune depense reelle.

    python -m nexus_agents.scenarios.reserve_prioritaire --log nexus_agents/preuves/reserve_prioritaire.log
"""
from __future__ import annotations

import argparse
from pathlib import Path

from nexus_core import Client
from nexus_core.tempdb import TempCluster

from ..gateway import ModelGateway
from ..models import ModelOutput, StubLocalModel
from ..trace import Trace, TracedClient

COST = 150      # centimes par appel cloud (1,50 EUR) : cout REEL, regle apres chaque appel


class FixedCostCloud:
    kind, name, simulated = "cloud", "Modèle cloud (simulé)", True

    def generate(self, task, payload, system_prompt=None):
        return ModelOutput({"ok": True, "notes": []}, 500, 100, COST, self.name, True)


def run(log_path: str | None = None, echo: bool = True) -> dict:
    cluster = TempCluster(54352).start()
    db = cluster.new_database()
    lines: list = []
    steps: list = []
    try:
        adm = cluster.connect(db, "postgres")

        def clock(iso):
            adm.execute("DELETE FROM nexus.clock_override"); adm.execute("INSERT INTO nexus.clock_override VALUES (%s::timestamptz)", (iso,))

        def say(msg):
            lines.append(msg)
            if echo:
                print(msg)

        clock("2026-10-05T10:00:00Z")
        adm.execute("UPDATE nexus.policy SET daily_api_cap_cents = 500, priority_reserve_daily_cents = 300, priority_min_score = 4")
        w = Client.connect(**cluster.conninfo(db, "nexus_worker"))
        trace = Trace()
        gw = ModelGateway(TracedClient(w, trace, "Passerelle de modèles", "nexus_worker"), trace, StubLocalModel(), FixedCostCloud())
        scores = {"LEAD-BAS": 3, "LEAD-HAUT-A": 5, "LEAD-HAUT-B": 4}
        for lead, sc in scores.items():
            w.record_lead_score(lead, sc, "scenario")
        say("# Preuve : réserve prioritaire quotidienne — base PostgreSQL réelle, modèle cloud SIMULÉ à 1,50 € par appel")
        say("# Politique : plafond quotidien API 5,00 € · réserve prioritaire 3,00 € · score minimum 4/5 · tâches éligibles : final_check, closing")
        say("# Enveloppe mensuelle d'exploitation : 240,00 € (la réserve puise DANS cette enveloppe, elle ne l'augmente pas)")
        say(f"# Scores enregistrés en base : {scores}")
        say("")

        def snapshot():
            s = w.budget_status()
            return (f"jour {s['daily_api']['committed'] / 100:.2f}/{s['daily_api']['cap'] / 100:.2f} € · "
                    f"réserve {s['priority_reserve']['committed'] / 100:.2f}/{s['priority_reserve']['cap'] / 100:.2f} € · "
                    f"mois {s['operating']['committed'] / 100:.2f}/{s['operating']['cap'] / 100:.2f} €")

        n = {"i": 0}

        def call(label, task, lead, expect):
            n["i"] += 1
            before = len(trace.events)
            r = gw.run(task, {"body": "texte du devis", "expected_price": "490"}, caller="Hermes", allow_cloud=True, est_cents=COST,
                       idem=f"scenario-{n['i']}", lead_ref=lead)
            code = r.code
            used_reserve = any(e.code == "ok_priority_reserve" for e in trace.events[before:])
            outcome = "ACCEPTÉ via RÉSERVE PRIORITAIRE" if used_reserve else ("accepté (plafond normal)" if r.ok else f"REFUSÉ ({code})")
            say(f"[{len(steps) + 1:02d}] {label:<54} lead={lead:<12} tâche={task:<11} → {outcome:<36} | {snapshot()}")
            steps.append({"label": label, "lead": lead, "task": task, "ok": r.ok, "code": code, "reserve": used_reserve, "expect": expect})
            assert (r.ok, used_reserve) == expect, f"attendu {expect}, obtenu {(r.ok, used_reserve)} ({code})"
            return r

        say("-- 1. le plafond quotidien se remplit avec des appels ordinaires (leads de score bas)")
        call("appel ordinaire n°1", "final_check", "LEAD-BAS", (True, False))
        call("appel ordinaire n°2", "final_check", "LEAD-BAS", (True, False))
        call("appel ordinaire n°3", "final_check", "LEAD-BAS", (True, False))
        say("-- 2. plafond quotidien atteint pour un appel de 1,50 € (4,50 € déjà engagés sur 5,00 €)")
        call("appel ordinaire n°4 : refusé, plafond du jour", "final_check", "LEAD-BAS", (False, False))
        call("lead score 3 : la réserve ne lui est PAS ouverte", "final_check", "LEAD-BAS", (False, False))
        say("-- 3. un lead High-Ticket (score >= 4) passe le plafond grâce à la réserve")
        call("HIGH-TICKET A (score 5), final_check", "final_check", "LEAD-HAUT-A", (True, True))
        call("HIGH-TICKET A (score 5), closing", "closing", "LEAD-HAUT-A", (True, True))
        say("-- 4. la réserve est bornée : 3,00 € par jour, deux appels de 1,50 € suffisent à l'épuiser")
        call("HIGH-TICKET B (score 4), final_check : réserve épuisée", "final_check", "LEAD-HAUT-B", (False, False))
        say("-- 5. la réserve ne couvre que final_check et closing")
        call("HIGH-TICKET A, deep_check : tâche non éligible", "deep_check", "LEAD-HAUT-A", (False, False))
        say("-- 6. le lendemain, plafond et réserve sont renouvelés")
        clock("2026-10-06T10:00:00Z")
        call("HIGH-TICKET B, jour suivant (plafond normal)", "final_check", "LEAD-HAUT-B", (True, False))

        say("")
        say("-- Ce que la base a enregistré (extrait du journal d'audit, chaîne de hachage vérifiée par la base) :")
        rows = adm.execute("""SELECT seq, event, payload->>'lead', payload->>'task', payload->>'priority_reserve', payload->>'code', payload->>'priorite_refusee'
                                FROM nexus.audit_log WHERE event IN ('budget_reserved','budget_refused') ORDER BY seq""").fetchall()
        for seq, ev, lead, task, prio, code, why in rows:
            if ev == "budget_reserved":
                say(f"   audit #{seq:<3} budget_reserved lead={lead or '-':<12} tâche={task or '-':<11} réserve_prioritaire={prio}")
            else:
                say(f"   audit #{seq:<3} budget_refused  code={code:<28} raison_priorité_refusée={why or '-'}")
        chain = w.verify_audit()
        env_month = w.budget_status()["operating"]
        say("")
        say(f"-- Chaîne d'audit : {'intacte' if chain is None else 'ROMPUE à la ligne ' + str(chain)} · enveloppe mensuelle utilisée : "
            f"{env_month['committed'] / 100:.2f} € sur {env_month['cap'] / 100:.2f} € (jamais dépassée par la réserve)")
        say("-- Limite : le rôle de base « worker » est partagé par tous les agents ; un agent compromis pourrait enregistrer un faux score. "
            "Le score est écrit une seule fois, journalisé, et la réserve reste plafonnée à 3,00 €/jour.")
        report = {"steps": steps, "audit_chain": chain, "operating": env_month, "lines": lines, "audit_rows": [list(map(str, r)) for r in rows]}
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(log_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report
    finally:
        cluster.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="nexus_agents/preuves/reserve_prioritaire.log")
    a = ap.parse_args()
    run(a.log)
