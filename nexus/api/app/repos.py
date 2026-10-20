from __future__ import annotations
import json
from pathlib import Path
from . import audit
from .db import J
from .errors import Invalid


def _items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("depots", "dépôts", "repositories", "repos", "items", "archives"):
            if isinstance(data.get(key), list):
                return data[key]
    raise Invalid("Format d'inventaire non reconnu (liste ou objet contenant une liste)", code="bad_inventory")


def import_inventory(conn, path: str | Path, actor: str = "cli") -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    created = skipped = 0
    for it in _items(data):
        if isinstance(it, str):
            it = {"name": it}
        name = next((it.get(k) for k in ("name", "nom", "full_name", "repo", "archive") if it.get(k)), None)
        if not name:
            raise Invalid(f"Entrée sans nom : {str(it)[:80]}", code="bad_inventory_entry")
        url = next((it.get(k) for k in ("url", "html_url", "clone_url", "lien") if it.get(k)), None)
        r = conn.execute("""INSERT INTO repositories(name, url, source, metadata) VALUES (%s,%s,%s,%s)
                            ON CONFLICT (name) DO NOTHING RETURNING id""",
                         (str(name), url, str(path), J(it))).fetchone()
        created += 1 if r else 0
        skipped += 0 if r else 1
    audit.record(conn, actor, "repositories.imported", "repository", None, details={"created": created, "skipped": skipped})
    return {"created": created, "skipped": skipped}
