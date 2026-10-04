"""File de taches durable : reprise apres plantage, relances, taches mortes, dedoublonnage."""
import threading

import psycopg
import pytest


def lead(i=1):
    return {"id": f"L{i}", "company": f"Societe {i}", "email": f"c{i}@societe{i}.example"}


def test_enqueue_is_idempotent_and_dedupes_by_key(env):
    w = env.client("worker")
    a = w.enqueue("lead:L1", "process_lead", lead(1), "domain:societe1.example")
    b = w.enqueue("lead:L1", "process_lead", lead(1), "domain:societe1.example")
    assert a.ok and b.ok and a.id == b.id
    dup = w.enqueue("lead:L1bis", "process_lead", lead(1), "domain:societe1.example")
    assert not dup.ok and dup.code == "duplicate"
    assert w.task_status() == {"queued": 1}


def test_bad_inputs_and_size_limit(env):
    w = env.client("worker")
    assert w.enqueue("", "process_lead", lead()).code == "bad_input"
    assert w.enqueue("x", "launch_missiles", lead()).code == "bad_input"
    assert w.enqueue("y", "process_lead", {"blob": "a" * 25000}).code == "bad_input"


def test_roles_are_separated(env):
    for role in ("censor", "transport", "founder"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            env.client(role).enqueue("x", "process_lead", lead())
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        env.client("censor").claim_task()
    assert env.client("founder").task_status() == {}


def test_claim_complete_and_idempotent_completion(env):
    w = env.client("worker")
    w.enqueue("lead:L1", "process_lead", lead(1))
    t = w.claim_task()
    assert t.kind == "process_lead" and t.attempt == 1 and t.payload["company"] == "Societe 1"
    assert w.claim_task() is None                           # deja pris
    assert w.complete_task(t.task_id, {"status": "sent"}).ok
    assert w.complete_task(t.task_id, {"status": "sent"}).ok
    assert w.task_status() == {"done": 1}


def test_failure_is_retried_with_growing_delay(env):
    w = env.client("worker")
    w.enqueue("lead:L1", "process_lead", lead(1))
    t = w.claim_task()
    assert w.fail_task(t.task_id, "timeout modele", 60).code == "retry"
    assert w.claim_task() is None                           # pas avant 60 s
    env.set_clock("2026-10-05T10:01:01Z")
    t2 = w.claim_task()
    assert t2.task_id == t.task_id and t2.attempt == 2
    assert w.fail_task(t2.task_id, "timeout modele", 60).code == "retry"
    env.set_clock("2026-10-05T10:02:30Z")                   # 2e echec : delai 120 s, pas encore du
    assert w.claim_task() is None
    env.set_clock("2026-10-05T10:03:10Z")
    assert w.claim_task().attempt == 3


def test_dead_after_max_attempts_and_founder_is_told(env):
    w = env.client("worker")
    w.enqueue("lead:L1", "process_lead", lead(1))
    for n in range(3):
        env.set_clock(f"2026-10-05T1{n}:30:00Z")
        t = w.claim_task()
        assert t.attempt == n + 1
        res = w.fail_task(t.task_id, "erreur persistante", 1)
    assert res.code == "dead" and w.task_status() == {"dead": 1}
    env.set_clock("2026-10-06T10:00:00Z")
    assert w.claim_task() is None
    notes = env.client("founder").notifications()
    assert [n["kind"] for n in notes] == ["needs_human"] and "abandonnée" in notes[0]["text"]


def test_crashed_runner_is_recovered_when_its_lease_expires(env):
    w = env.client("worker")
    w.enqueue("lead:L1", "process_lead", lead(1))
    crashed = w.claim_task(lease_seconds=30)               # l'executant plante ici : il ne rend jamais la tache
    assert env.client("worker").claim_task() is None       # tant que le bail court, personne d'autre ne la prend
    env.set_clock("2026-10-05T10:01:00Z")
    again = env.client("worker").claim_task()
    assert again.task_id == crashed.task_id and again.attempt == 2


def test_lease_expiring_after_the_last_attempt_kills_the_task(env):
    w = env.client("worker")
    w.enqueue("lead:L1", "process_lead", lead(1))
    for n in range(3):
        env.set_clock(f"2026-10-05T1{n}:00:00Z")
        assert w.claim_task(lease_seconds=30).attempt == n + 1   # trois plantages de suite
    env.set_clock("2026-10-05T13:00:00Z")
    assert w.claim_task() is None and w.task_status() == {"dead": 1}


def test_each_task_is_taken_once_under_concurrency(env):
    w = env.client("worker")
    for i in range(10):
        w.enqueue(f"lead:L{i}", "process_lead", lead(i))
    got = []

    def runner():
        c = env.client("worker")
        while (t := c.claim_task()) is not None:
            got.append(t.task_id)
            c.complete_task(t.task_id, {})

    ths = [threading.Thread(target=runner) for _ in range(6)]
    [x.start() for x in ths]
    [x.join() for x in ths]
    assert sorted(got) == list(range(1, 11)) and w.task_status() == {"done": 10}
