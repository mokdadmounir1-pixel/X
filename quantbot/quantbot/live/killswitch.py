"""Arrêt d'urgence : tant qu'il est actif, AUCUNE nouvelle entrée n'est possible.

Causes : fichier KILL présent, drapeau persistant (déclenché par le programme), intention à l'état INCONNU non résolue,
limite FTMO atteinte. Il ne se lève jamais seul : seule une action humaine explicite (`clear`) le fait.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .state import StateStore


class KillSwitch:
    def __init__(self, state: StateStore, kill_file: str | Path = "KILL") -> None:
        self.state = state
        self.kill_file = Path(kill_file)

    def reasons(self) -> list[str]:
        out = []
        if self.kill_file.exists():
            out.append(f"fichier {self.kill_file.name} présent")
        flag = self.state.get("kill")
        if flag:
            out.append(f"déclenché : {flag}")
        unk = self.state.unknown_intents()
        if unk:
            out.append(f"{len(unk)} intention(s) à l'état INCONNU non résolue(s)")
        return out

    def active(self) -> bool:
        return bool(self.reasons())

    def trigger(self, reason: str) -> None:
        if not self.state.get("kill"):
            self.state.set("kill", reason)
            self.state.log("CRITICAL", "killswitch", reason)

    def clear(self, confirm: str) -> None:
        """Action HUMAINE : lève le drapeau persistant (pas le fichier KILL ni les intentions INCONNUES, à traiter à la main)."""
        if confirm != "JE_COMPRENDS":
            raise PermissionError("confirmation explicite requise")
        self.state.delete("kill")
        self.state.log("WARNING", "killswitch_clear", "levé par un humain")
