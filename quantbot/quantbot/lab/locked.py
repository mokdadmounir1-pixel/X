"""Période verrouillée : séparée dès le départ, lisible une seule fois par spécification.

Différences voulues avec un simple marqueur de fichier :
- pas de `force` : une 2e lecture de la même spec est refusée ;
- la lecture est inscrite dans le registre AVANT l'exécution (un crash compte quand même) ;
- chaque lecture augmente le nombre d'essais du DSR : on ne peut pas « consommer » la
  période verrouillée avec des dizaines de variantes sans que le verdict s'en ressente.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from .registry import TrialRegistry


class LockedSliceError(PermissionError):
    pass


class LockedSlice:
    def __init__(self, full: pd.DataFrame, lock_start: pd.Timestamp) -> None:
        self.__full = full
        self.lock_start = lock_start

    def __repr__(self) -> str:  # ne révèle aucune donnée
        return f"LockedSlice(lock_start={self.lock_start})"

    def _open(self) -> pd.DataFrame:
        return self.__full


def split_locked(df: pd.DataFrame, lock_months: int = 12, min_frac: float = 0.20):
    """(données de recherche, période verrouillée). Le verrou couvre >= lock_months ET >= min_frac."""
    t0, t1 = df.index[0], df.index[-1]
    lock_start = min(t1 - pd.DateOffset(months=lock_months), t1 - (t1 - t0) * min_frac)
    research = df[df.index < lock_start].copy()
    if len(research) < 50:
        raise LockedSliceError("Pas assez de données avant la période verrouillée")
    return research, LockedSlice(df, lock_start)


def final_evaluation(locked: LockedSlice, spec_hash: str, registry: TrialRegistry,
                     fn: Callable[[pd.DataFrame, pd.Timestamp], dict]) -> dict:
    """Exécute fn(données_complètes, début_du_verrou) UNE SEULE FOIS pour cette spec."""
    if registry.locked_reads(spec_hash) > 0:
        raise LockedSliceError(f"Période verrouillée déjà lue pour la spec {spec_hash[:12]} : relire le résultat publié")
    registry.append("locked_read", {"spec_hash": spec_hash, "lock_start": str(locked.lock_start)})
    result = fn(locked._open(), locked.lock_start)
    registry.append("locked_result", {"spec_hash": spec_hash, "result": result})
    return result
