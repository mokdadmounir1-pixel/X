"""Contrôle de santé du socle : chaîne d'audit, migrations, droits des rôles. Lecture seule. Code de sortie 0 = sain."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from init_db import load_env   # noqa: E402


def main(out=print) -> int:
    load_env(Path(__file__).with_name(".env"))
    e = os.environ
    base = dict(host=e.get("NEXUS_PG_HOST", "127.0.0.1"), port=int(e.get("NEXUS_PG_PORT", "5433")), dbname=e.get("NEXUS_DB", "nexus"), autocommit=True)
    problems = []
    with psycopg.connect(user="nexus_owner", password=e.get("NEXUS_OWNER_PASSWORD") or None, **base) as o:
        broken = o.execute("SELECT nexus.verify_audit_chain()").fetchone()[0]
        out(f"chaîne d'audit : {'intacte' if broken is None else 'ROMPUE à la ligne ' + str(broken)}")
        if broken is not None:
            problems.append("audit")
        vers = [r[0] for r in o.execute("SELECT version FROM nexus.schema_migrations ORDER BY 1").fetchall()]
        out(f"migrations : {vers}")
        if "002_observabilite_closing_evo_reserve" not in vers:
            problems.append("migration 002 absente")
        # aucun rôle applicatif ne doit avoir de droit direct sur les tables
        direct = o.execute("""SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants
                               WHERE table_schema = 'nexus' AND grantee IN ('nexus_worker','nexus_censor','nexus_founder','nexus_transport')""").fetchall()
        out(f"droits directs sur tables pour les rôles applicatifs : {len(direct)}")
        if direct:
            problems.append(f"{len(direct)} droit(s) direct(s) sur tables")
        sup = o.execute("SELECT rolname FROM pg_roles WHERE rolname LIKE 'nexus\\_%' AND (rolsuper OR rolcreaterole OR rolcreatedb)").fetchall()
        out(f"rôles nexus_* avec privilèges d'administration : {len(sup)}")
        if sup:
            problems.append("rôle(s) trop privilégié(s)")
    out("SAIN" if not problems else "PROBLÈME : " + "; ".join(problems))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
