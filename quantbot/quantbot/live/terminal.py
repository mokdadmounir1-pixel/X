"""Chemin du terminal MetaTrader 5 : paramètre explicite > variable d'environnement QUANTBOT_MT5_TERMINAL > chemin par défaut SI le fichier existe > aucun (MT5 trouve alors le terminal ouvert par lui-même).

Un chemin explicite est transmis tel quel (s'il est faux, MT5 renvoie une erreur lisible) ; l'environnement et le défaut ne sont utilisés que s'ils existent (jamais un chemin par défaut inexistant qui ferait échouer la connexion).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

ENV = "QUANTBOT_MT5_TERMINAL"


def resolve_terminal(explicit: Optional[str] = None, default: Optional[str] = None) -> Optional[str]:
    if explicit:
        return explicit
    for cand in (os.environ.get(ENV), default):
        if cand and Path(cand).exists():
            return cand
    return None


def mt5_initialize(mt5: Any, explicit: Optional[str] = None, default: Optional[str] = None, timeout: int = 15000) -> bool:
    path = resolve_terminal(explicit, default)
    return bool(mt5.initialize(path, timeout=timeout) if path else mt5.initialize(timeout=timeout))
