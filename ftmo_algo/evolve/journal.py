"""Journal des changements : append-only (JSONL), une ligne par décision, avec les chiffres qui la justifient."""
from __future__ import annotations
import json
from pathlib import Path


class EvoJournal:
    def __init__(self, path=None, label="SYNTHÉTIQUE"):
        self.path = Path(path) if path else None
        self.label = label
        self.events: list[dict] = []

    def log(self, event: str, algo: str, asof, **kw):
        row = {"event": event, "algo": algo, "asof": str(asof), "label": self.label, **kw}
        self.events.append(row)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=_js) + "\n")

    def count(self, event: str, algo: str | None = None) -> int:
        return sum(1 for e in self.events if e["event"] == event and (algo is None or e["algo"] == algo))


def _js(o):
    if hasattr(o, "item"):
        return o.item()
    return str(o)
