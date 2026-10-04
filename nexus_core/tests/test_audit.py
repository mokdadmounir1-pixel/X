"""Audit : chaine de hachage, rejeu, restauration."""
import subprocess
import threading

import psycopg
import pytest

from nexus_core.tests.conftest import PG_BIN


def test_chain_is_valid_and_immutable_through_normal_paths(env):
    w = env.client("worker")
    for i in range(5):
        w.reserve(f"k{i}", "operations", 100)
    assert w.verify_audit() is None
    a = env.admin()
    with pytest.raises(psycopg.errors.RaiseException, match="immutable_table"):
        a.execute("UPDATE nexus.audit_log SET payload = '{}'::jsonb")
    with pytest.raises(psycopg.errors.RaiseException, match="immutable_table"):
        a.execute("DELETE FROM nexus.audit_log")
    with pytest.raises(psycopg.errors.RaiseException, match="immutable_table"):
        a.execute("TRUNCATE nexus.audit_log")


def test_tampering_by_an_administrator_is_detected(env):
    w = env.client("worker")
    for i in range(6):
        w.reserve(f"k{i}", "operations", 100)
    a = env.admin()
    a.execute("ALTER TABLE nexus.audit_log DISABLE TRIGGER audit_no_mod")
    a.execute("UPDATE nexus.audit_log SET payload = payload || '{\"x\":1}'::jsonb WHERE seq = 3")
    a.execute("ALTER TABLE nexus.audit_log ENABLE TRIGGER audit_no_mod")
    assert w.verify_audit() == 3
    # suppression d'une ligne : la chaine casse sur la suivante
    a.execute("ALTER TABLE nexus.audit_log DISABLE TRIGGER audit_no_mod")
    a.execute("UPDATE nexus.audit_log SET payload = payload - 'x' WHERE seq = 3")
    a.execute("DELETE FROM nexus.audit_log WHERE seq = 4")
    a.execute("ALTER TABLE nexus.audit_log ENABLE TRIGGER audit_no_mod")
    assert w.verify_audit() == 5


def test_concurrent_writers_do_not_fork_the_chain(env):
    def go(i):
        env.client("worker").reserve(f"par{i}", "operations", 10)

    ths = [threading.Thread(target=go, args=(i,)) for i in range(30)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    a = env.admin()
    assert a.execute("SELECT count(*) FROM nexus.audit_log").fetchone()[0] >= 30
    assert a.execute("SELECT count(DISTINCT prev_hash) = count(*) FROM nexus.audit_log").fetchone()[0]
    assert env.client("worker").verify_audit() is None


def test_dump_and_restore_keep_balances_and_chain(env, cluster):
    w = env.client("worker")
    for i in range(4):
        w.reserve(f"k{i}", "operations", 250)
    w.reserve("r", "research", 1200)
    before = w.budget_status()
    dump = subprocess.run(
        [f"{PG_BIN}/pg_dump", "-h", cluster["host"], "-p", str(cluster["port"]), "-U", "postgres", "-d", env.dbname],
        check=True, capture_output=True, text=True).stdout
    name = env.dbname + "_restore"
    with psycopg.connect(dbname="postgres", user="postgres", autocommit=True, host=cluster["host"], port=cluster["port"]) as c:
        c.execute(f'CREATE DATABASE "{name}" OWNER nexus_owner')
    try:
        subprocess.run([f"{PG_BIN}/psql", "-h", cluster["host"], "-p", str(cluster["port"]), "-U", "postgres",
                        "-d", name, "-v", "ON_ERROR_STOP=1", "-q"], input=dump, check=True, capture_output=True, text=True)
        from nexus_core import Client
        r = Client.connect(host=cluster["host"], port=cluster["port"], dbname=name, user="nexus_worker")
        assert r.budget_status() == before
        assert r.verify_audit() is None
        # les droits survivent a la restauration
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            r.conn.execute("SELECT * FROM nexus.audit_log")
        r.close()
    finally:
        with psycopg.connect(dbname="postgres", user="postgres", autocommit=True, host=cluster["host"], port=cluster["port"]) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
