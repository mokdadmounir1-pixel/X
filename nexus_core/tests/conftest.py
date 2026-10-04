"""Cluster PostgreSQL temporaire, base modele, une base neuve par test."""
import itertools
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import psycopg
import pytest

from nexus_core import Client

PG_BIN = os.environ.get("PG_BIN", "/usr/lib/postgresql/16/bin")
HERE = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("NEXUS_TEST_PGPORT", "54329"))
ROLES = ["worker", "censor", "founder", "transport"]
_counter = itertools.count(1)


def _run_as_postgres(*cmd, **kw):
    return subprocess.run(["runuser", "-u", "postgres", "--", *cmd], check=True,
                          capture_output=True, text=True, **kw)


@pytest.fixture(scope="session")
def cluster():
    base = Path(tempfile.mkdtemp(prefix="nexus_pg_"))
    os.chmod(base, 0o777)
    data, sock = base / "data", base / "sock"
    sock.mkdir()
    os.chmod(sock, 0o777)
    _run_as_postgres(f"{PG_BIN}/initdb", "-D", str(data), "--auth=trust", "-E", "UTF8", "--no-sync")
    opts = f"-k {sock} -p {PORT} -c listen_addresses= -c fsync=off -c synchronous_commit=off -c max_connections=200"
    _run_as_postgres(f"{PG_BIN}/pg_ctl", "-D", str(data), "-o", opts, "-w", "-l", str(base / "log"), "start")
    info = {"host": str(sock), "port": PORT, "base": base}
    boot = (HERE / "bootstrap.sql").read_text()
    with psycopg.connect(dbname="postgres", user="postgres", autocommit=True, host=info["host"], port=PORT) as c:
        c.execute(boot)
        c.execute("CREATE DATABASE nexus_template OWNER nexus_owner")
    with psycopg.connect(dbname="nexus_template", user="nexus_owner", autocommit=True, host=info["host"], port=PORT) as c:
        c.execute((HERE / "schema.sql").read_text())
        c.execute((HERE / "seed_principals.sql").read_text())
    yield info
    try:
        _run_as_postgres(f"{PG_BIN}/pg_ctl", "-D", str(data), "-m", "immediate", "-w", "stop")
    finally:
        shutil.rmtree(base, ignore_errors=True)


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
                (c.close if hasattr(c, "close") else None)()
            except Exception:
                pass


@pytest.fixture()
def env(cluster):
    name = f"t{next(_counter)}_{os.getpid()}"
    with psycopg.connect(dbname="postgres", user="postgres", autocommit=True,
                         host=cluster["host"], port=cluster["port"]) as c:
        c.execute(f'CREATE DATABASE "{name}" TEMPLATE nexus_template OWNER nexus_owner')
    e = Env(cluster, name)
    e.set_clock("2026-10-05T10:00:00Z")  # lundi 12:00 a Paris, cycle 0, mois d'octobre
    yield e
    e.close()
    with psycopg.connect(dbname="postgres", user="postgres", autocommit=True,
                         host=cluster["host"], port=cluster["port"]) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
