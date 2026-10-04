"""Trace des connexions entre agents : qui parle a qui, pour dire quoi, avec quel resultat."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class Event:
    seq: int
    ms: int
    src: str
    dst: str
    kind: str
    summary: str
    ok: Optional[bool] = None
    code: Optional[str] = None
    cost_cents: int = 0
    detail: dict = field(default_factory=dict)


class Trace:
    def __init__(self):
        self.events: list[Event] = []
        self.ctx: dict = {}          # contexte courant (ex. lead en cours), copie dans chaque evenement
        self._t0 = time.monotonic()

    def emit(self, src: str, dst: str, kind: str, summary: str, *, ok=None, code=None, cost_cents=0, **detail) -> Event:
        ev = Event(len(self.events) + 1, int((time.monotonic() - self._t0) * 1000), src, dst, kind,
                   summary, ok, code, cost_cents, {**self.ctx, **detail})
        self.events.append(ev)
        return ev

    def to_list(self) -> list[dict]:
        return [asdict(e) for e in self.events]


def _preview(v: Any, n: int = 70) -> Any:
    if isinstance(v, str):
        return v if len(v) <= n else v[: n - 1] + "…"
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return f"<{type(v).__name__}>"


class TracedClient:
    """Enveloppe un Client nexus_core : chaque appel a la base devient un evenement de trace."""

    def __init__(self, client, trace: Trace, actor: str, db_role: str):
        self._c, self._trace, self._actor, self._role = client, trace, actor, db_role

    def __getattr__(self, name: str):
        attr = getattr(self._c, name)
        if not callable(attr):
            return attr

        def call(*args, **kw):
            try:
                out = attr(*args, **kw)
            except Exception as exc:
                self._trace.emit(self._actor, "Noyau Nexus", "db", name, ok=False, code=type(exc).__name__,
                                 role=self._role, error=str(exc).splitlines()[0][:120])
                raise
            ok = code = None
            if hasattr(out, "ok") and hasattr(out, "code"):
                ok, code = out.ok, out.code
            self._trace.emit(self._actor, "Noyau Nexus", "db", name, ok=ok, code=code, role=self._role,
                             args=[_preview(a) for a in args])
            return out

        return call
