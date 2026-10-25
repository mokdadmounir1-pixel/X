"""Console Windows (cp1252) : ne jamais perdre un résultat à cause d'un caractère d'affichage.

Un `print` avec « → », « ≥ » ou « é » peut lever UnicodeEncodeError sous cp1252 APRÈS que les résultats ont été écrits (incident C8 : 12 essais sur 13 non exécutés).
`safe_console()` passe stdout/stderr en UTF-8 et, à défaut, remplace ce qui ne s'encode pas au lieu de planter.
"""
from __future__ import annotations

import sys


def safe_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            try:
                stream.reconfigure(errors="replace")
            except (AttributeError, ValueError, OSError):
                pass
