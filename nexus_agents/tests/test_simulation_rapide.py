"""La simulation rapide à 3 leads doit prouver les 4 corrections dans une seule exécution."""
from nexus_agents.scenarios import simulation_rapide


def test_simulation_rapide_prouve_les_quatre_corrections():
    r = simulation_rapide.run(echo=False)
    failed = [c for c in r["checks"] if not c["ok"]]
    assert not failed, failed
    assert {c["correction"] for c in r["checks"]} >= {0, 1, 2, 3, 4}
    assert r["audit_chain"] is None
