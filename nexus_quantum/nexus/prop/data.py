"""Chargement CSV (export MT5/autre): colonnes date + close (en-tetes insensibles a la casse).

Verifie: dates croissantes, prix > 0, pas de doublon. Alignement multi-actifs par
intersection de dates. La provenance (hash du fichier) est retournee pour le registre.
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path


def load_close_csv(path: str | Path) -> tuple[list[str], list[float], str]:
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    if not rows:
        raise ValueError(f"{path}: vide")
    keys = {k.lower().strip().strip("<>"): k for k in rows[0]}
    dk, ck = keys.get("date") or keys.get("time"), keys.get("close")
    if not dk or not ck:
        raise ValueError(f"{path}: colonnes date/close absentes: {list(rows[0])}")
    dates, px = [], []
    for r in rows:
        d, c = r[dk].strip()[:10], float(r[ck])
        if c <= 0:
            raise ValueError(f"{path}: prix non positif a {d}")
        if dates and d <= dates[-1]:
            raise ValueError(f"{path}: dates non strictement croissantes a {d}")
        dates.append(d); px.append(c)
    return dates, px, sha


def align(series: dict[str, tuple[list[str], list[float]]]) -> tuple[list[str], dict[str, list[float]]]:
    common = set.intersection(*(set(d) for d, _ in series.values()))
    dates = sorted(common)
    out = {}
    for s, (d, p) in series.items():
        m = dict(zip(d, p))
        out[s] = [m[x] for x in dates]
    return dates, out
