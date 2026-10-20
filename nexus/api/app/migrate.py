"""Exécuteur de migrations : ordre lexical, somme de contrôle, une transaction par fichier."""
from __future__ import annotations
import hashlib
from pathlib import Path
import psycopg

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def migrate(url: str, directory: Path = MIGRATIONS) -> list[str]:
    applied_now: list[str] = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(9187002)")
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations(
                name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())""")
            done = dict(conn.execute("SELECT name, checksum FROM schema_migrations").fetchall())
            for path in sorted(directory.glob("*.sql")):
                sql = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode()).hexdigest()
                if path.name in done:
                    if done[path.name] != checksum:
                        raise RuntimeError(f"Migration {path.name} modifiée après application : refus")
                    continue
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute("INSERT INTO schema_migrations(name, checksum) VALUES (%s,%s)", (path.name, checksum))
                applied_now.append(path.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(9187002)")
    return applied_now
