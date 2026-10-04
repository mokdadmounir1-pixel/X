"""Lecture d'un manifeste de qualification : seules les taches reellement qualifiees passent en local."""
import json
from pathlib import Path

from .runner import HERE, sha256_file


class QualificationError(Exception):
    pass


def load_qualified_tasks(path: str, *, accept_provisional: bool = False, thresholds: Path = HERE / "thresholds.json") -> set:
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    if m.get("thresholds_sha256") != sha256_file(thresholds):
        raise QualificationError("les seuils ont change depuis la mesure : manifeste invalide, refaire le banc")
    ok = {"qualifié"} | ({"provisoire_conforme"} if accept_provisional else set())
    return {t for t, r in m["tasks"].items() if r["verdict"] in ok}
