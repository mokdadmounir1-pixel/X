"""Racine des données de l'application : le dossier du projet, ou le dossier de l'exécutable une fois compilé (PyInstaller)."""
from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):                  # exécutable : specs/, reports/, data/, runtime/ vivent À CÔTÉ du .exe (données de l'utilisateur)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def bundle_dir() -> Path:
    """Ressources embarquées (interface web) : dans le paquet en exécution normale, dans _MEIPASS une fois compilé."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "quantbot" / "gui"
