"""Registre d'experiences immuable (append-only, chaine de hachage).

Raison d'etre: interdire la suppression des experiences negatives et fournir
le nombre reel d'essais (N) necessaire au Deflated Sharpe Ratio.
Condition d'echec: toute alteration ou suppression de ligne => verify() False.
Limite: la chaine detecte l'alteration, elle ne l'empeche pas; l'ancrage
externe du dernier hash (hors machine) est requis pour une garantie forte.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

GENESIS = "0" * 64
STATUSES = {"VERIFIE", "SYNTHETIQUE", "HYPOTHESE"}  # [VERIFIE]/[SYNTHETIQUE]/[HYPOTHESE]
REQUIRED = ("hypothesis", "data_ref", "code_ref", "params", "costs", "dates", "status")


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(prev: str, body: dict) -> str:
    return hashlib.sha256((prev + _canon(body)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Entry:
    seq: int
    body: dict
    prev: str
    hash: str


class ExperimentRegistry:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def entries(self) -> list[Entry]:
        out = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    d = json.loads(line)
                    out.append(Entry(d["seq"], d["body"], d["prev"], d["hash"]))
        return out

    def record(self, **body) -> Entry:
        missing = [k for k in REQUIRED if k not in body]
        if missing:
            raise ValueError(f"champs obligatoires manquants: {missing}")
        if body["status"] not in STATUSES:
            raise ValueError(f"status doit etre dans {sorted(STATUSES)}")
        body.setdefault("outcome", "pending")  # les negatifs sont enregistres comme les positifs
        es = self.entries()
        prev = es[-1].hash if es else GENESIS
        seq = len(es)
        h = _hash(prev, {"seq": seq, **body})
        entry = Entry(seq, body, prev, h)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(_canon({"seq": seq, "body": body, "prev": prev, "hash": h}) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return entry

    def verify(self) -> tuple[bool, str]:
        prev = GENESIS
        for i, e in enumerate(self.entries()):
            if e.seq != i:
                return False, f"seq discontinue a {i} (suppression/insertion)"
            if e.prev != prev:
                return False, f"chaine rompue a {i}"
            if _hash(prev, {"seq": e.seq, **e.body}) != e.hash:
                return False, f"contenu altere a {i}"
            prev = e.hash
        return True, "ok"

    def head(self) -> str:
        es = self.entries()
        return es[-1].hash if es else GENESIS

    def n_trials(self, family: str | None = None) -> int:
        """Nombre d'essais, negatifs inclus: entree pour le DSR."""
        es = self.entries()
        if family is None:
            return len(es)
        return sum(1 for e in es if e.body.get("family") == family)
