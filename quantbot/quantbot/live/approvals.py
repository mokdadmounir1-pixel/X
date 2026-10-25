"""Approbation HUMAINE : le programme ne l'écrit jamais. Sans approbation valide, le bot reste en OBSERVATION (aucun ordre).

Format de `approved_strategies.json` (à rédiger à la main) :
{"approved": [{"id": "amd", "instrument": "XAUUSD", "spec": "specs/inst_strategies_v1.json",
               "spec_sha256": "<empreinte du fichier de spec>", "approved_by": "nom", "date": "2026-10-26"}]}
L'empreinte lie l'approbation à la spec EXACTE : modifier la spec invalide l'approbation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_approval(strategy_id: str, instrument: str, spec_path: str | Path, approvals_path: str | Path) -> tuple[bool, str]:
    ap = Path(approvals_path)
    if not ap.exists():
        return False, "fichier d'approbation absent : mode observation"
    try:
        data = json.loads(ap.read_text(encoding="utf-8"))
        entries = data["approved"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return False, "fichier d'approbation illisible : mode observation"
    for e in entries:
        if e.get("id") == strategy_id and e.get("instrument") == instrument:
            if not e.get("approved_by") or not e.get("date"):
                return False, "approbation sans signataire/date : refusée"
            if not Path(spec_path).exists():
                return False, "spec introuvable : refusée"
            if e.get("spec_sha256") != file_sha256(spec_path):
                return False, "empreinte de spec différente : la spec a changé depuis l'approbation"
            return True, f"approuvée par {e['approved_by']} le {e['date']}"
    return False, f"stratégie {strategy_id}/{instrument} non approuvée : mode observation"
