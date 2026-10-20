"""Sondes de disponibilité des services. Les URL viennent de la table `services` (jamais d'une requête)."""
from __future__ import annotations
import httpx
from . import audit
from .db import tx


def probe_all(settings, actor: str = "system", correlation_id=None) -> list[dict]:
    with tx(settings.database_url) as c:
        rows = c.execute("SELECT * FROM services ORDER BY id").fetchall()
    results = []
    for s in rows:
        if s["status"] == "disabled":
            continue
        status, detail = "unknown", None
        if s["id"] in ("postgres", "api"):
            status = "up"
        elif s["id"] == "ollama":
            try:
                r = httpx.get(f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=2.0)
                status, detail = ("up" if r.status_code < 500 else "degraded"), f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                status, detail = "down", type(e).__name__
        elif s["url"]:
            try:
                r = httpx.get(s["url"], timeout=2.0)
                status, detail = ("up" if r.status_code < 500 else "degraded"), f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                status, detail = "down", type(e).__name__
        results.append((s["id"], status, detail))
    with tx(settings.database_url) as c:
        for sid, status, detail in results:
            c.execute("UPDATE services SET status=%s, detail=%s, checked_at=now() WHERE id=%s", (status, detail, sid))
        audit.record(c, actor, "services.probed", "service", None, correlation_id, details={s: st for s, st, _ in results})
        return c.execute("SELECT * FROM services ORDER BY id").fetchall()
