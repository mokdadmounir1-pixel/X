"""Découpage recherche / période VERROUILLÉE. La période verrouillée n'est jamais chargée dans les objets
utilisés pendant la recherche ; elle n'est accessible que via `final_evaluation` (une seule fois)."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd


class LockedSlice:
    def __init__(self, dfs_full, lock_start):
        self._full = dfs_full
        self.lock_start = lock_start
        self._open = False

    def _data(self):
        if not self._open:
            raise PermissionError("période verrouillée : accès interdit pendant la recherche")
        return self._full


class ResearchData:
    """Contient UNIQUEMENT les données antérieures au verrou."""

    def __init__(self, dfs, lock_start, span):
        self.dfs = dfs
        self.lock_start = lock_start
        self.span = span


def split_locked(dfs: dict[str, pd.DataFrame], lock_months: int = 12, min_frac: float = 0.20):
    t0 = min(d.index[0] for d in dfs.values()); t1 = max(d.index[-1] for d in dfs.values())
    span = t1 - t0
    by_months = t1 - pd.DateOffset(months=lock_months)
    by_frac = t1 - span * min_frac
    lock_start = min(by_months, by_frac)      # le plus ancien des deux : verrou ≥ 12 mois ET ≥ 20 %
    res = {k: d[d.index < lock_start] for k, d in dfs.items()}
    return ResearchData(res, lock_start, span), LockedSlice(dfs, lock_start)


def final_evaluation(locked: LockedSlice, fn, marker_dir="results", tag="", force=False):
    """Exécute `fn(full_dfs, lock_start)` UNE SEULE FOIS ; un marqueur disque empêche toute 2e évaluation."""
    Path(marker_dir).mkdir(exist_ok=True, parents=True)
    marker = Path(marker_dir) / f"locked_eval_{tag}.json"
    if marker.exists() and not force:
        raise RuntimeError(f"période verrouillée DÉJÀ évaluée ({marker}) : relire le résultat publié, "
                           "pas de 2e évaluation (utiliser force=True ne fait que tracer l'infraction).")
    locked._open = True
    try:
        out = fn(locked._data(), locked.lock_start)
    finally:
        locked._open = False
    marker.write_text(json.dumps({"tag": tag, "lock_start": str(locked.lock_start), "forced": bool(force),
                                  "result": out}, default=str, indent=1))
    return out
