"""Scenario complet sur une vraie base : ce qui doit se produire, et surtout ce qui ne doit pas."""
import pytest

from nexus_agents import demo
from nexus_agents.agents import SENTINEL


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    return demo.run(str(tmp_path_factory.mktemp("demo")))


def by_lead(report):
    return {o["lead"]: o["status"] for o in report["outcomes"]}


def test_each_lead_takes_the_expected_path(report):
    assert by_lead(report) == {"L1": "sent", "L2": "sent", "L3": "refusé_par_le_fondateur", "L4": "écarté_sourcing",
                               "L5": "écarté_sourcing", "L6": "écarté_rédaction", "L7": "sent"}


def first_contacts(report):
    return [m for m in report["sent"] if not m["attachments"]]


def test_only_approved_clean_messages_were_handed_to_the_sink(report):
    # L1 est rattrape apres le plantage du transport : il part apres L2 ; le devis de L1 part en dernier, avec sa piece jointe
    assert sorted(m["to"] for m in first_contacts(report)) == ["anne.roche@menuiserie-roche.example", "claire.martin@agence-lumiere.example",
                                                               "m.aubry@transports-aubry.example"]
    for m in first_contacts(report):
        assert "garanti" not in m["body"].lower() and "RIB" not in m["body"] and "STOP" in m["body"]
    assert len(report["sent"]) == 4 and report["sent"][-1]["attachments"]


def test_weak_draft_was_rejected_then_corrected_by_a_different_role(report):
    db = [e for e in report["events"] if e["kind"] == "db" and e["detail"].get("lead") == "L2"]
    roles = {e["summary"]: e["detail"]["role"] for e in db}
    assert roles["review"] == "nexus_censor" and roles["create_message"] == "nexus_worker" and roles["approve"] == "nexus_founder"
    verdicts = [e for e in report["events"] if e["kind"] == "verdict" and e["detail"].get("lead") == "L2"]
    assert [v["ok"] for v in verdicts] == [False, True]
    assert {m["version"] for m in report["messages"] if "aubry" in m["company"]} == {1, 2}


def test_hidden_instructions_were_ignored_and_flagged_not_obeyed(report):
    kinds = [n["kind"] for n in report["notifications"]]
    assert kinds.count("injection_attempt") == 2          # une dans la source de L3, une dans la reponse de L1
    inj = [e for e in report["events"] if e["kind"] == "injection"]
    assert {e["detail"]["rule"] for e in inj} >= {"ignorer_regles", "nouveau_role"}
    assert not any(n["kind"] == "ready_to_sign" and n["ref"] == "L3" for n in report["notifications"])


def test_setter_stops_before_signature_with_the_exact_sentence(report):
    ready = {n["ref"]: n for n in report["notifications"] if n["kind"] == "ready_to_sign"}
    assert set(ready) == {"L1", "L7"} and all(n["text"].startswith(SENTINEL) for n in ready.values())
    assert any(n["kind"] == "needs_human" and n["ref"] == "L1" for n in report["notifications"])   # une reponse positive n'est pas « pret a signer »


def test_opposition_is_respected_everywhere(report):
    assert "m.aubry@transports-aubry.example" in report["suppression"]
    l2 = [r for r in report["rejections"] if r["lead"] == "L2" and r["stage"] == "redaction"]
    assert l2 and "opposition enregistrée le 2026-10-05" in l2[0]["motif_exact"] and l2[0]["preuve_source"]["type"] == "suppression"
    l6 = [r for r in report["rejections"] if r["lead"] == "L6"]
    assert l6 and l6[0]["preuve_source"]["recipient_sha256"] and "imprimerie" not in str(l6[0]["preuve_source"])   # jamais l'adresse en clair


def test_budget_charges_actual_cost_and_refuses_the_expensive_check(report):
    res = report["reservations"]
    assert len(res) == 3 and all(r["status"] == "settled" and r["category"] == "operations" for r in res)   # 2 final_check + 1 closing
    assert report["budget"]["operating"]["committed"] == sum(r["actual"] for r in res) > 0
    assert report["budget"]["research"]["committed"] == 0
    refused = [e for e in report["events"] if e["kind"] == "refus"]
    assert refused and refused[0]["code"] == "budget_exceeded:research_cycle"


def test_audit_chain_is_intact_and_permissions_are_separated(report):
    assert report["audit"]["verify"] is None and report["audit"]["count"] >= 90
    perm = {p["function"]: p["roles"] for p in report["permissions"]}
    assert perm["approve"] == ["founder"] and perm["submit_review"] == ["censor"]
    assert perm["create_message"] == ["worker"] and perm["claim_outbox"] == ["transport"]
    assert perm["decide_evolution"] == ["founder"] and perm["create_document"] == ["worker"] and perm["propose_evolution"] == ["worker"]
    assert "audit" not in perm and "block_message" not in perm and "seed_prompt" not in perm and "deploy_evolution" not in perm


def test_crashed_transport_is_recovered_through_the_durable_queue(report):
    ev = report["events"]
    assert any(e["kind"] == "plantage" for e in ev)
    failed = [e for e in ev if e["kind"] == "échec"]
    assert len(failed) == 1 and failed[0]["code"] == "retry" and failed[0]["detail"]["lead"] == "L1"
    attempts = [e["summary"] for e in ev if e["kind"] == "tâche_reçue" and e["detail"].get("lead") == "L1" and "process_lead" in e["summary"]]
    assert len(attempts) == 2 and attempts[1].endswith("tentative 2")
    assert report["tasks"].get("done") == len(report["task_rows"]) == 10
    assert not any(r["state"] in ("dead", "queued", "running") for r in report["task_rows"])


def test_a_retry_creates_no_duplicate_message_and_no_double_billing(report):
    first = next(m for m in report["messages"] if m["id"] == 1)
    assert first["state"] == "sent" and first["attempts"] == 2 and first["company"].startswith("claire.martin")
    assert len([m for m in report["messages"] if m["version"] == 1 and m["company"].startswith("claire.martin")]) == 2   # contact + devis, pas de doublon
    assert any(e["code"] == "cache_hit" for e in report["events"])


def test_duplicate_lead_is_refused_by_the_queue_itself(report):
    dup = [e for e in report["events"] if e["kind"] == "rejet" and e["detail"].get("rejection_detail", {}).get("preuve_source", {}).get("type") == "file_taches"]
    assert dup and dup[0]["detail"]["lead"] == "L5"
    assert len([r for r in report["task_rows"] if r["kind"] == "process_lead"]) == 6      # L1, L2, L3, L4, L6, L7 : jamais L5


# ====================================================================== 1. observabilite : plus de zone aveugle
def test_every_rejected_lead_has_a_complete_rejection_detail(report):
    for o in report["outcomes"]:
        if o["status"] in ("sent", "approved"):
            assert o["rejection_detail"] is None
            continue
        d = o["rejection_detail"]
        assert d and len(d["motif_exact"]) >= 8 and d["preuve_source"].get("type") and 0 <= d["indice_confiance"] <= 1, o
    assert {o["lead"] for o in report["outcomes"] if o["rejection_detail"]} == {"L3", "L4", "L5", "L6"}


def test_database_holds_the_same_rejections_with_exact_reasons(report):
    stages = {(r["lead"], r["stage"]) for r in report["rejections"]}
    assert {("L4", "sourcing"), ("L5", "sourcing"), ("L6", "redaction"), ("L2", "redaction"), ("L2", "revue"),
            ("L3", "decision_fondateur"), ("L7", "closing")} <= stages
    by = {(r["lead"], r["stage"]): r for r in report["rejections"]}
    assert "aucune URL source https" in by[("L4", "sourcing")]["motif_exact"] and by[("L4", "sourcing")]["indice_confiance"] == 1.0
    assert by[("L3", "decision_fondateur")]["base_confiance"] == "decision_humaine"
    assert "400" in by[("L7", "closing")]["motif_exact"] and "490" in by[("L7", "closing")]["motif_exact"]
    assert "promesse" in by[("L2", "revue")]["motif_exact"]
    assert all(r["motif_exact"] and r["preuve_source"] and r["indice_confiance"] is not None for r in report["rejections"])


def test_the_call_log_shows_the_precise_reason_of_each_dismissal(report):
    dismissals = [e for e in report["events"] if e["detail"].get("rejection_detail")]
    assert len(dismissals) >= 10
    for e in dismissals:
        assert e["detail"]["rejection_detail"]["motif_exact"] in e["summary"] or e["kind"] == "issue", e["summary"]
    generic = [e for e in report["events"] if e["kind"] in ("rejet", "issue") and e["ok"] is False and not e["detail"].get("rejection_detail")]
    assert generic == []          # aucun rejet sans detail dans le journal


# ====================================================================== 2. closing automatique
def test_ready_to_sign_produces_a_quote_and_a_payment_link_in_the_approval_queue(report):
    ok = [c for c in report["closings"] if c["ok"]]
    assert len(ok) == 1 and ok[0]["lead"] == "L1" and ok[0]["link_simulated"] is True and ok[0]["decided"] == "approved"
    doc = report["documents"][0]
    assert doc["lead"] == "L1" and doc["kind"] == "devis" and doc["sha256"] == ok[0]["sha256"] and doc["bytes"] > 1000
    v = doc["variables"]
    assert (v["nom"], v["entreprise"], v["prix_eur_ht"]) == ("Claire Martin", "Agence Lumière (fictive)", 490) and "Audit" in v["offre"] and v["perimetre"]
    notif = [n for n in report["notifications"] if n["kind"] == "document_ready"]
    assert len(notif) == 1 and "VALIDATION FINALE" in notif[0]["text"]


def test_nothing_is_sent_to_the_client_before_the_founder_approves_the_quote(report):
    ev = report["events"]
    seq_ready = next(e["seq"] for e in ev if e["code"] == "document_ready")
    seq_approve = next(e["seq"] for e in ev if e["kind"] == "décision" and e["detail"].get("lead") == "L1" and e["seq"] > seq_ready)
    seq_send = next(e["seq"] for e in ev if e["kind"] == "envoi" and "pièce jointe" in e["summary"])
    assert seq_ready < seq_approve < seq_send
    review = [e for e in ev if e["kind"] == "verdict" and e["seq"] > seq_ready - 20 and e["detail"].get("lead") == "L1"]
    assert review                                        # le devis a ete relu par le Censeur avant d'arriver au fondateur


def test_the_sent_quote_carries_the_approved_pdf_and_the_payment_link(report):
    m = report["sent"][-1]
    att = m["attachments"][0]
    doc = report["documents"][0]
    assert att["sha256"] == doc["sha256"] and doc["sha256"] in m["body"]
    assert "https://paiement.invalid/simulation/" in m["body"] and "245 € HT" in m["body"] and "STOP" in m["body"]


def test_a_price_mismatch_blocks_the_quote_with_an_exact_reason(report):
    blocked = [c for c in report["closings"] if not c["ok"]]
    assert len(blocked) == 1 and blocked[0]["lead"] == "L7" and blocked[0]["code"] == "prix_incoherent"
    assert any(n["kind"] == "closing_blocked" and "400" in n["text"] for n in report["notifications"])
    assert len(report["documents"]) == 1             # aucun document pour L7


# ====================================================================== 3. evolutions deployees
def test_an_approved_evolution_is_deployed_and_logged_and_used_immediately(report):
    ev = {e["agent"]: e for e in report["evolutions"]}
    assert ev["Rédacteur"]["status"] == "APPROUVÉ" and ev["Rédacteur"]["deployed_version"] == 2
    assert ev["Sourcing"]["status"] == "PROPOSÉ" and ev["Sourcing"]["deployed_version"] is None      # en attente : rien n'est deploye
    assert [d["message"] for d in report["deployment_log"]] == ["Prompt Agent Rédacteur mis à jour vers Version 2"]
    active = {p["agent"]: p["version"] for p in report["prompts"]}
    assert active["Rédacteur"] == 2 and active["Sourcing"] == 1


def test_the_new_prompt_changed_the_agent_behaviour_without_restart(report):
    uses = {e["detail"]["lead"]: e["detail"]["prompt_version"] for e in report["events"]
            if e["kind"] == "demande" and e["detail"].get("prompt_agent") == "Rédacteur" and "draft_message" in e["summary"]}
    assert uses["L2"] == 1 and uses["L7"] == 2
    l7 = [e for e in report["events"] if e["kind"] == "verdict" and e["detail"].get("lead") == "L7"]
    assert [v["ok"] for v in l7[:1]] == [True]       # meme modele « faible » : plus de promesse, accepte du premier coup
    assert any(e["code"] == "prompt_live" for e in report["events"])


# ====================================================================== 4. reserve prioritaire dans le rapport
def test_budget_status_exposes_daily_cap_and_priority_reserve(report):
    b = report["budget"]
    assert b["daily_api"]["cap"] == 500 and b["priority_reserve"]["cap"] == 300 and b["priority_reserve"]["min_score"] == 4
