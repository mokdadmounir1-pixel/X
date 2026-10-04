"""init_db.py : idempotent, charge schéma + migrations, refuse les mots de passe faibles. check.py : sain après init.

Limite : le cluster de test est en authentification « trust » ; la vérification des mots de passe par PostgreSQL n'est pas testée ici.
"""
import importlib.util
from pathlib import Path

import pytest

from nexus_core.tempdb import TempCluster

D = Path(__file__).resolve().parents[2] / "deploy" / "local"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, D / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


@pytest.fixture()
def pg(monkeypatch):
    cl = TempCluster(54360).start()
    for k, v in dict(NEXUS_PG_HOST=cl.host, NEXUS_PG_PORT=str(cl.port), NEXUS_DB="nexus_deploy", NEXUS_PG_TRUST="1").items():
        monkeypatch.setenv(k, v)
    try:
        yield cl
    finally:
        cl.stop()


def test_init_puis_check_puis_idempotence(pg):
    init, check = _load("init_db"), _load("check")
    log = []
    assert init.main(log.append) == 0, log
    assert any("migrations appliquées : 002" in l for l in log) or any("002_observabilite" in l for l in log)
    log2 = []
    assert init.main(log2.append) == 0, log2
    assert any("aucune (déjà à jour)" in l for l in log2), log2
    out = []
    assert check.main(out.append) == 0, out
    assert out[-1] == "SAIN"


def test_mots_de_passe_faibles_refuses(monkeypatch):
    init = _load("init_db")
    monkeypatch.delenv("NEXUS_PG_TRUST", raising=False)
    for r in ("OWNER", "WORKER", "CENSOR", "FOUNDER", "TRANSPORT"):
        monkeypatch.setenv(f"NEXUS_{r}_PASSWORD", "CHANGER")
    monkeypatch.setenv("NEXUS_PG_ADMIN_PASSWORD", "court")
    log = []
    assert init.main(log.append) == 2
    assert "ERREUR" in log[0]
