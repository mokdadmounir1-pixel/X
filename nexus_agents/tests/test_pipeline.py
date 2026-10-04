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
    assert by_lead(report) == {"L1": "sent", "L2": "sent", "L3": "refusé_par_le_fondateur",
                               "L4": "écarté_sourcing", "L5": "écarté_sourcing", "L6": "écarté_rédaction"}


def test_only_approved_clean_messages_were_handed_to_the_sink(report):
    # L1 est rattrape apres le plantage du transport : il part apres L2, l'ordre n'est donc pas celui des leads
    assert sorted(m["to"] for m in report["sent"]) == ["claire.martin@agence-lumiere.example", "m.aubry@transports-aubry.example"]
    for m in report["sent"]:
        assert "garanti" not in m["body"].lower() and "RIB" not in m["body"] and "STOP" in m["body"]


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
    assert not any(n["kind"] == "ready_to_sign" and "L3" in n["ref"] for n in report["notifications"])


def test_setter_stops_before_signature_with_the_exact_sentence(report):
    ready = [n for n in report["notifications"] if n["kind"] == "ready_to_sign"]
    assert len(ready) == 1 and ready[0]["text"].startswith(SENTINEL) and ready[0]["ref"] == "L1"
    positive = [n for n in report["notifications"] if n["kind"] == "needs_human"]
    assert any(n["ref"] == "L1" for n in positive)         # une reponse positive n'est pas "pret a signer"


def test_opposition_is_respected_everywhere(report):
    assert "m.aubry@transports-aubry.example" in report["suppression"]
    follow = [e for e in report["events"] if e["kind"] == "résultat" and e["detail"].get("lead") == "L2"]
    assert follow and follow[0]["code"] == "suppressed"
    l6 = [e for e in report["events"] if e["summary"] == "create_message" and e["detail"].get("lead") == "L6"]
    assert l6 and l6[0]["code"] == "suppressed"


def test_budget_charges_actual_cost_and_refuses_the_expensive_check(report):
    res = report["reservations"]
    assert len(res) == 2 and all(r["status"] == "settled" and r["category"] == "operations" for r in res)
    assert report["budget"]["operating"]["committed"] == sum(r["actual"] for r in res) > 0
    assert report["budget"]["research"]["committed"] == 0
    refused = [e for e in report["events"] if e["kind"] == "refus"]
    assert refused and refused[0]["code"] == "budget_exceeded:research_cycle"


def test_audit_chain_is_intact_and_permissions_are_separated(report):
    assert report["audit"]["verify"] is None and report["audit"]["count"] >= 20
    perm = {p["function"]: p["roles"] for p in report["permissions"]}
    assert perm["approve"] == ["founder"] and perm["submit_review"] == ["censor"]
    assert perm["create_message"] == ["worker"] and perm["claim_outbox"] == ["transport"]
    assert "audit" not in perm and "block_message" not in perm        # fonctions internes : aucun role


def test_evolution_is_proposed_never_deployed(report):
    assert report["evolution"] and all("rien n'est déployé" in p["statut"] for p in report["evolution"])
    assert not report["breaker"]["open"]


def test_crashed_transport_is_recovered_through_the_durable_queue(report):
    ev = report["events"]
    assert any(e["kind"] == "plantage" for e in ev)
    failed = [e for e in ev if e["kind"] == "échec"]
    assert len(failed) == 1 and failed[0]["code"] == "retry" and failed[0]["detail"]["lead"] == "L1"
    attempts = [e["summary"] for e in ev if e["kind"] == "tâche_reçue" and e["detail"].get("lead") == "L1" and "process_lead" in e["summary"]]
    assert len(attempts) == 2 and attempts[1].endswith("tentative 2")
    assert report["tasks"] == {"done": 8} or report["tasks"].get("done") == len(report["task_rows"])
    assert not any(r["state"] in ("dead", "queued", "running") for r in report["task_rows"])


def test_a_retry_creates_no_duplicate_message_and_no_double_billing(report):
    l1 = [m for m in report["messages"] if m["company"].startswith("claire.martin")]
    assert len(l1) == 1 and l1[0]["state"] == "sent" and l1[0]["attempts"] == 2    # 2 reservations d'envoi : la 1re a plante
    assert len(report["reservations"]) == 2
    assert any(e["code"] == "cache_hit" for e in report["events"])


def test_duplicate_lead_is_refused_by_the_queue_itself(report):
    dup = [e for e in report["events"] if e["kind"] == "rejet" and e["code"] == "duplicate"]
    assert dup and dup[0]["detail"]["lead"] == "L5"
    lead_tasks = [r for r in report["task_rows"] if r["kind"] == "process_lead"]
    assert len(lead_tasks) == 5          # L1, L2, L3, L4, L6 : le doublon L5 n'a jamais ete mis en file
