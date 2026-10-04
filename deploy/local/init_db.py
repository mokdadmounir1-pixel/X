"""Initialise (ou met à niveau) la base Nexus d'un PostgreSQL existant. Idempotent : peut être relancé sans risque.

Étapes : rôles (bootstrap.sql) → mots de passe → base `nexus` → schéma + principaux (première fois seulement)
→ migrations manquantes → vérification de la chaîne d'audit.
Les mots de passe sont lus dans l'environnement (jamais en argument, jamais affichés).

    python deploy/local/init_db.py            # lit .env s'il existe, sinon l'environnement
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from nexus_core.tempdb import apply_migrations   # noqa: E402

CORE = ROOT / "nexus_core"
ROLES = ("owner", "worker", "censor", "founder", "transport")
PLACEHOLDERS = {"", "CHANGER"}


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main(out=print) -> int:
    load_env(Path(__file__).with_name(".env"))
    env = os.environ
    host, port, dbname = env.get("NEXUS_PG_HOST", "127.0.0.1"), int(env.get("NEXUS_PG_PORT", "5433")), env.get("NEXUS_DB", "nexus")
    admin_user = env.get("NEXUS_PG_ADMIN_USER", "postgres")
    trust = env.get("NEXUS_PG_TRUST") == "1"      # tests seulement : cluster temporaire en authentification « trust »
    pw = {r: env.get(f"NEXUS_{r.upper()}_PASSWORD", "") for r in ROLES}
    admin_pw = env.get("NEXUS_PG_ADMIN_PASSWORD", "")
    if not trust:
        weak = [n for n, v in {**{f"NEXUS_{r.upper()}_PASSWORD": pw[r] for r in ROLES}, "NEXUS_PG_ADMIN_PASSWORD": admin_pw}.items()
                if v in PLACEHOLDERS or len(v) < 16]
        if weak:
            out(f"ERREUR : mot(s) de passe absent(s), « CHANGER » ou de moins de 16 caractères : {', '.join(weak)}")
            return 2
        if len(set(pw.values()) | {admin_pw}) < len(ROLES) + 1:
            out("ERREUR : chaque rôle doit avoir un mot de passe distinct.")
            return 2
    base = dict(host=host, port=port, autocommit=True)
    if not trust:
        base["connect_timeout"] = 10

    with psycopg.connect(dbname="postgres", user=admin_user, password=admin_pw or None, **base) as a:
        a.execute((CORE / "bootstrap.sql").read_text())
        for r in ROLES:
            if pw[r]:
                a.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(f"nexus_{r}"), sql.Literal(pw[r])))
        if not a.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone():
            a.execute(sql.SQL("CREATE DATABASE {} OWNER nexus_owner").format(sql.Identifier(dbname)))
            out(f"base « {dbname} » créée")
        a.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(dbname)))
        for r in ROLES:
            a.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(dbname), sql.Identifier(f"nexus_{r}")))

    with psycopg.connect(dbname=dbname, user="nexus_owner", password=pw["owner"] or None, **base) as o:
        if not o.execute("SELECT to_regnamespace('nexus') IS NOT NULL").fetchone()[0]:
            o.execute((CORE / "schema.sql").read_text())
            o.execute((CORE / "seed_principals.sql").read_text())
            out("schéma de base chargé")
        applied = apply_migrations(o)
        out(f"migrations appliquées : {', '.join(applied) if applied else 'aucune (déjà à jour)'}")
        broken = o.execute("SELECT nexus.verify_audit_chain()").fetchone()[0]
        if broken is not None:
            out(f"ERREUR : chaîne d'audit rompue à la ligne {broken}")
            return 1
        versions = [r[0] for r in o.execute("SELECT version FROM nexus.schema_migrations ORDER BY version").fetchall()]
    out(f"OK · base « {dbname} » · migrations enregistrées : {versions} · chaîne d'audit intacte")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
