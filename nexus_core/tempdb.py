"""Cluster PostgreSQL temporaire pour les tests et la demonstration.

Demarre un cluster jetable (utilisateur systeme `postgres`, socket Unix, sans reseau),
y charge le schema Nexus dans une base modele, et fournit une base neuve a la demande.
Rien n'est installe sur la machine et rien n'ecoute sur le reseau.
"""
from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import psycopg

PG_BIN = os.environ.get("PG_BIN", "/usr/lib/postgresql/16/bin")
HERE = Path(__file__).resolve().parent
_counter = itertools.count(1)


class TempCluster:
    def __init__(self, port: int = 54329):
        self.port = port
        self.base = Path(tempfile.mkdtemp(prefix="nexus_pg_"))
        os.chmod(self.base, 0o777)
        self.sock = self.base / "sock"
        self.sock.mkdir()
        os.chmod(self.sock, 0o777)
        self.data = self.base / "data"
        self.host = str(self.sock)

    def _pg(self, *cmd):
        return subprocess.run(["runuser", "-u", "postgres", "--", *cmd], check=True,
                              capture_output=True, text=True)

    def start(self) -> "TempCluster":
        self._pg(f"{PG_BIN}/initdb", "-D", str(self.data), "--auth=trust", "-E", "UTF8", "--no-sync")
        opts = (f"-k {self.sock} -p {self.port} -c listen_addresses= -c fsync=off "
                f"-c synchronous_commit=off -c max_connections=200")
        self._pg(f"{PG_BIN}/pg_ctl", "-D", str(self.data), "-o", opts, "-w", "-l", str(self.base / "log"), "start")
        with self.connect("postgres", "postgres") as c:
            c.execute((HERE / "bootstrap.sql").read_text())
            c.execute("CREATE DATABASE nexus_template OWNER nexus_owner")
        with self.connect("nexus_template", "nexus_owner") as c:
            c.execute((HERE / "schema.sql").read_text())
            c.execute((HERE / "seed_principals.sql").read_text())
        return self

    def connect(self, dbname: str, user: str) -> psycopg.Connection:
        return psycopg.connect(dbname=dbname, user=user, autocommit=True, host=self.host, port=self.port)

    def conninfo(self, dbname: str, user: str) -> dict:
        return dict(host=self.host, port=self.port, dbname=dbname, user=user)

    def new_database(self) -> str:
        name = f"t{next(_counter)}_{os.getpid()}"
        with self.connect("postgres", "postgres") as c:
            c.execute(f'CREATE DATABASE "{name}" TEMPLATE nexus_template OWNER nexus_owner')
        return name

    def drop_database(self, name: str) -> None:
        with self.connect("postgres", "postgres") as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    def stop(self) -> None:
        try:
            self._pg(f"{PG_BIN}/pg_ctl", "-D", str(self.data), "-m", "immediate", "-w", "stop")
        finally:
            shutil.rmtree(self.base, ignore_errors=True)
