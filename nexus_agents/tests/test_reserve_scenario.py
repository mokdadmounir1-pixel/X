"""La preuve demandee : un lead High-Ticket franchit le plafond quotidien via la reserve prioritaire."""
from nexus_agents.scenarios import reserve_prioritaire as rp


def test_high_ticket_lead_passes_the_daily_cap_and_the_log_proves_it(tmp_path):
    log = tmp_path / "reserve.log"
    r = rp.run(str(log), echo=False)
    steps = {i + 1: s for i, s in enumerate(r["steps"])}
    assert [steps[i]["reserve"] for i in (6, 7)] == [True, True] and all(steps[i]["ok"] for i in (6, 7))        # High-Ticket passe via la reserve
    assert not steps[4]["ok"] and steps[4]["code"] == "budget_exceeded:daily_api"                              # appel ordinaire : plafond atteint
    assert not steps[5]["ok"] and not steps[5]["reserve"]                                                       # score 3 : reserve fermee
    assert steps[8]["code"] == "priority_reserve_exhausted"                                                     # la reserve est bornee
    assert steps[9]["code"] == "budget_exceeded:daily_api"                                                      # deep_check non eligible
    assert steps[10]["ok"] and not steps[10]["reserve"]                                                         # lendemain : renouvele
    assert r["audit_chain"] is None and r["operating"]["committed"] <= r["operating"]["cap"]
    text = log.read_text(encoding="utf-8")
    assert "ACCEPTÉ via RÉSERVE PRIORITAIRE" in text and "priority_reserve_exhausted" in text and "score_insuffisant" in text
    assert "tache_non_eligible" in text and "chaîne d'audit : intacte" in text.lower().replace("chaîne d’audit", "chaîne d'audit")
