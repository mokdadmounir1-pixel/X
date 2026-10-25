"""Validation croisée purgée avec embargo (López de Prado, AFML ch. 7)."""
from __future__ import annotations

import numpy as np


class PurgedKFold:
    """K blocs contigus. Un échantillon i a une étiquette qui s'étend sur [i, label_end[i]]. Pour chaque bloc de test, on retire de l'apprentissage :
    (1) tout échantillon dont l'intervalle chevauche le bloc de test (purge) ; (2) les `embargo` échantillons qui suivent le bloc (embargo)."""

    def __init__(self, n_splits: int = 5, embargo_frac: float = 0.01) -> None:
        if n_splits < 2:
            raise ValueError("n_splits >= 2")
        self.n_splits, self.embargo_frac = n_splits, embargo_frac

    def split(self, label_end: np.ndarray):
        label_end = np.asarray(label_end); n = len(label_end); idx = np.arange(n)
        emb = int(np.ceil(n * self.embargo_frac)); bounds = np.linspace(0, n, self.n_splits + 1).astype(int)
        for k in range(self.n_splits):
            a, b = bounds[k], bounds[k + 1]; test = idx[a:b]
            t_start, t_end = test[0], label_end[a:b].max()
            overlap = (idx <= t_end) & (label_end >= t_start)          # intervalle [i, label_end[i]] touche le test
            embargoed = (idx >= b) & (idx < b + emb)
            train = idx[~overlap & ~embargoed & ~np.isin(idx, test)]
            yield train, test
