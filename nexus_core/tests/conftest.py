"""Cluster PostgreSQL temporaire, base modele, une base neuve par test."""
import os

import psycopg
import pytest

from nexus_core import Client
from nexus_core.tempdb import PG_BIN, TempCluster  # noqa: F401  (PG_BIN reexporte pour les tests)

PORT = int(os.environ.get("NEXUS_TEST_PGPORT", "54329"))


@pytest.fixture(scope="session")
def cluster():
    c = TempCluster(PORT).start()
    yield {"host": c.host, "port": c.port, "base": c.base, "_cluster": c}
    c.stop()


class Env:
    def __init__(self, cluster, dbname):
        self.cluster, self.dbname = cluster, dbname
        self._clients = []

    def conninfo(self, user):
        return dict(host=self.cluster["host"], port=self.cluster["port"], dbname=self.dbname, user=user)

    def client(self, role: str) -> Client:
        c = Client.connect(**self.conninfo(f"nexus_{role}"))
        self._clients.append(c)
        return c

    def admin(self):
        c = psycopg.connect(autocommit=True, **self.conninfo("postgres"))
        self._clients.append(c)
        return c

    def set_clock(self, iso: str):
        a = self.admin()
        a.execute("DELETE FROM nexus.clock_override")
        a.execute("INSERT INTO nexus.clock_override VALUES (%s::timestamptz)", (iso,))
        a.close()

    def set_policy(self, **cols):
        a = self.admin()
        for k, v in cols.items():
            a.execute(f"UPDATE nexus.policy SET {k} = %s", (v,))
        a.close()

    def close(self):
        for c in self._clients:
            try:
                c.close()
            except Exception:
                pass


@pytest.fixture()
def env(cluster):
    tc = cluster["_cluster"]
    name = tc.new_database()
    e = Env(cluster, name)
    e.set_clock("2026-10-05T10:00:00Z")  # lundi 12:00 a Paris, cycle 0, mois d'octobre
    yield e
    e.close()
    tc.drop_database(name)
