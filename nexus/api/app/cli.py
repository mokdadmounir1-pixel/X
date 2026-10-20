"""Outils d'administration : python -m app.cli <commande>."""
from __future__ import annotations
import argparse, getpass, os, sys
from .config import Settings
from .db import tx
from .migrate import migrate
from . import audit, repos
from .security import check_password_policy, hash_password


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nexus")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    cu = sub.add_parser("create-user")
    cu.add_argument("--username", required=True)
    cu.add_argument("--role", required=True, choices=["fondateur", "operateur", "lecture"])
    ir = sub.add_parser("import-repos")
    ir.add_argument("path")
    sub.add_parser("verify-audit")
    a = ap.parse_args(argv)
    s = Settings.from_env()
    if a.cmd == "migrate":
        print("appliquées :", migrate(s.database_url) or "aucune (déjà à jour)")
    elif a.cmd == "create-user":
        pw = os.environ.get("NEXUS_NEW_USER_PASSWORD") or getpass.getpass("Mot de passe (12+ caractères) : ")
        check_password_policy(a.username, pw)
        with tx(s.database_url) as c:
            c.execute("INSERT INTO users(username, password_hash, role) VALUES (%s,%s,%s)", (a.username, hash_password(pw), a.role))
            audit.record(c, "cli", "user.created", "user", a.username, details={"role": a.role})
        print(f"Utilisateur {a.username} ({a.role}) créé.")
    elif a.cmd == "import-repos":
        with tx(s.database_url) as c:
            print(repos.import_inventory(c, a.path))
    elif a.cmd == "verify-audit":
        with tx(s.database_url) as c:
            r = audit.verify(c)
        print(r)
        return 0 if r["ok"] else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
