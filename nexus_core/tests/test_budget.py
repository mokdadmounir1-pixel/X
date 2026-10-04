"""Budget : plafonds, cycle, mois de Paris, alertes, couts tardifs, concurrence, droits."""
import threading

import psycopg
import pytest

from nexus_core import Client

OPERATING = 24000   # 300 EUR - 60 EUR de reserve intouchable
RESEARCH = 6000
CYCLE = 3000


def test_reserve_up_to_cap_then_refuse(env):
    w = env.client("worker")
    for i in range(24):
        assert w.reserve(f"k{i}", "operations", 1000).ok
    r = w.reserve("k24", "operations", 1)
    assert not r.ok and r.code == "budget_exceeded:operating"
    assert w.budget_status()["operating"]["committed"] == OPERATING


def test_reserve_never_touches_untouchable_reserve(env):
    w = env.client("worker")
    assert not w.reserve("big", "operations", OPERATING + 1).ok
    assert w.budget_status()["reserve_untouchable"] == 6000


@pytest.mark.parametrize("cents", [None, 0, -5])
def test_unknown_or_invalid_cost_is_refused(env, cents):
    r = env.client("worker").reserve("x", "operations", cents)
    assert not r.ok and r.code == "unknown_cost"


def test_unknown_category_and_missing_idempotency_key(env):
    w = env.client("worker")
    assert w.reserve("a", "marketing", 100).code == "bad_category"
    assert w.reserve("", "operations", 100).code == "idem_required"


def test_idempotent_reservation(env):
    w = env.client("worker")
    a = w.reserve("same", "operations", 500)
    b = w.reserve("same", "operations", 500)
    assert a.ok and b.ok and a.id == b.id
    assert w.budget_status()["operating"]["committed"] == 500
    assert w.reserve("same", "operations", 600).code == "idem_conflict"


def test_research_cycle_cap_and_new_cycle(env):
    w = env.client("worker")
    assert w.reserve("r1", "research", CYCLE).ok
    r = w.reserve("r2", "research", 1)
    assert not r.ok and r.code == "budget_exceeded:research_cycle"
    # le 19 octobre (Paris) on entre dans le cycle 1 : le plafond de cycle repart
    env.set_clock("2026-10-19T10:00:00Z")
    assert w.budget_status()["cycle"]["id"] == 1
    assert w.reserve("r3", "research", CYCLE).ok
    # mais le plafond mensuel de recherche (60 EUR) tient
    r = w.reserve("r4", "research", 1)
    assert not r.ok and r.code == "budget_exceeded:research_month"


def test_cycle_is_derived_from_anchor_not_from_caller(env):
    w = env.client("worker")
    # J15 du premier cycle : 18 octobre 2026 (Paris) est encore le cycle 0
    env.set_clock("2026-10-18T21:00:00Z")   # 18 oct 23:00 a Paris
    assert w.budget_status()["cycle"]["id"] == 0
    env.set_clock("2026-10-18T22:30:00Z")   # 19 oct 00:30 a Paris
    assert w.budget_status()["cycle"]["id"] == 1


def test_research_cycle_spanning_two_months_is_summed_by_cycle(env):
    w = env.client("worker")
    env.set_clock("2026-10-31T10:00:00Z")    # cycle 1 (jour 27 -> 27//15 = 1), octobre
    assert w.reserve("c1", "research", 2000).ok
    env.set_clock("2026-11-01T10:00:00Z")    # novembre, jour 28 -> encore cycle 1
    assert w.budget_status()["cycle"]["id"] == 1
    r = w.reserve("c2", "research", 1500)
    assert not r.ok and r.code == "budget_exceeded:research_cycle"
    assert w.reserve("c3", "research", 1000).ok


def test_month_boundary_uses_paris_time(env):
    w = env.client("worker")
    env.set_clock("2026-10-31T22:30:00Z")    # 31 oct 23:30 a Paris (UTC+1)
    assert w.reserve("full", "operations", OPERATING).ok
    assert w.reserve("more", "operations", 1).code == "budget_exceeded:operating"
    env.set_clock("2026-10-31T23:30:00Z")    # 1er nov 00:30 a Paris
    assert w.budget_status()["month"] == "2026-11-01"
    assert w.reserve("nov", "operations", 1000).ok


def test_alerts_80_and_100_fire_once_each(env):
    w = env.client("worker")
    assert w.reserve("a", "operations", 19199).ok
    a = env.admin()
    assert a.execute("SELECT count(*) FROM nexus.budget_alert").fetchone()[0] == 0
    assert w.reserve("b", "operations", 1).ok            # 19200 = 80 %
    assert w.reserve("c", "operations", 100).ok           # pas de doublon
    rows = a.execute("SELECT scope, level FROM nexus.budget_alert ORDER BY level").fetchall()
    assert rows == [("operating", "80")]
    assert w.reserve("d", "operations", 24000 - 19300).ok  # 100 %
    assert not w.reserve("e", "operations", 1).ok
    assert not w.reserve("f", "operations", 1).ok
    rows = a.execute("SELECT scope, level FROM nexus.budget_alert ORDER BY level").fetchall()
    assert rows == [("operating", "100"), ("operating", "80")] or rows == [("operating", "80"), ("operating", "100")]
    assert len(rows) == 2


def test_settle_below_reservation_frees_capacity(env):
    w = env.client("worker")
    r = w.reserve("x", "operations", 5000)
    assert w.settle(r.id, 2000).ok
    assert w.budget_status()["operating"]["committed"] == 2000
    assert w.settle(r.id, 2000).ok                           # idempotent
    assert w.settle(r.id, 2500).code == "already_settled"


def test_release_only_when_reserved(env):
    w = env.client("worker")
    r = w.reserve("x", "operations", 700)
    assert w.release(r.id).ok and w.release(r.id).ok
    assert w.budget_status()["operating"]["committed"] == 0
    r2 = w.reserve("y", "operations", 700)
    w.settle(r2.id, 700)
    assert w.release(r2.id).code == "not_releasable"
    assert w.settle(r.id, 10).code == "released"


def test_late_overrun_is_kept_and_stops_the_month_of_origin(env):
    w = env.client("worker")
    big = w.reserve("big", "operations", OPERATING)
    assert big.ok
    env.set_clock("2026-11-03T10:00:00Z")                    # regle apres le changement de mois
    assert w.settle(big.id, OPERATING + 1500).ok
    a = env.admin()
    # le cout tardif reste attribue a octobre, il n'est pas ecrete
    assert a.execute("SELECT nexus.committed(DATE '2026-10-01')").fetchone()[0] == OPERATING + 1500
    assert a.execute("SELECT nexus.committed(DATE '2026-11-01')").fetchone()[0] == 0
    assert a.execute("SELECT count(*) FROM nexus.budget_stop WHERE period_month = DATE '2026-10-01'").fetchone()[0] == 1
    assert w.reserve("nov", "operations", 1000).ok            # novembre n'est pas bloque
    env.set_clock("2026-10-20T10:00:00Z")
    assert w.reserve("oct", "operations", 1).code == "budget_stopped"


def test_overrun_within_caps_does_not_stop(env):
    w = env.client("worker")
    r = w.reserve("x", "operations", 1000)
    assert w.settle(r.id, 1800).ok
    flagged = env.admin().execute("SELECT overrun FROM nexus.budget_reservation WHERE id = %s", (r.id,)).fetchone()[0]
    assert flagged is True
    assert w.reserve("y", "operations", 1000).ok


def test_concurrent_reservations_never_exceed_cap(env):
    results, errors = [], []

    def go(i):
        try:
            c = env.client("worker")
            results.append(c.reserve(f"par{i}", "operations", 1000).ok)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(40)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert sum(results) == 24
    assert env.client("worker").budget_status()["operating"]["committed"] == OPERATING


def test_roles_cannot_touch_tables_or_internal_functions(env):
    w = env.client("worker")
    for sql in [
        "INSERT INTO nexus.budget_reservation (idem_key, category, period_month, reserved_cents, description, requested_by) "
        "VALUES ('z','operations',DATE '2026-10-01',1,'x','x')",
        "UPDATE nexus.policy SET total_cents = 10000000",
        "SELECT * FROM nexus.audit_log",
        "DELETE FROM nexus.suppression",
        "INSERT INTO nexus.clock_override VALUES (now())",
        "SELECT nexus.audit('x', '{}'::jsonb)",
        "SELECT nexus.block_message(1, 'x')",
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            w.conn.execute(sql)


def test_reserve_function_has_no_time_parameter(env):
    # l'appelant ne peut pas choisir la date pour contourner un plafond de mois ou de cycle
    w = env.client("worker")
    with pytest.raises(psycopg.errors.UndefinedFunction):
        w.conn.execute("SELECT nexus.reserve_budget('t','operations',1,'x', now())")


def test_censor_cannot_spend(env):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        env.client("censor").reserve("x", "operations", 1)
