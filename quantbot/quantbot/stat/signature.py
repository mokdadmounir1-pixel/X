"""Signature d'un chemin linéaire par morceaux, tronquée au niveau 3, calculée EXACTEMENT par l'identité de Chen — brique de SIG-TDA.

Pour un chemin de dimension d : niveau 1 (d), niveau 2 (d^2), niveau 3 (d^3) ; d = 3 -> 39 caractéristiques. Un segment d'incrément D a pour signature exp(D) = (D, D(x)D/2, D(x)D(x)D/6) ; Chen : S(a * b) = S(a) (x) S(b).
Niveau 2 antisymétrique = aire de Lévy ; invariante par reparamétrisation temporelle et ne dépend que de la forme (ordre) du chemin.
"""
from __future__ import annotations

import numpy as np


def _mul(A: tuple, B: tuple) -> tuple:
    a1, a2, a3 = A; b1, b2, b3 = B
    return (a1 + b1, a2 + np.einsum("i,j->ij", a1, b1) + b2, a3 + np.einsum("ij,k->ijk", a2, b1) + np.einsum("i,jk->ijk", a1, b2) + b3)


def signature(path: np.ndarray) -> np.ndarray:
    """Vecteur aplati (niveaux 1, 2, 3) de la signature du chemin `path` (n points x d)."""
    path = np.asarray(path, float); d = path.shape[1]; S = (np.zeros(d), np.zeros((d, d)), np.zeros((d, d, d)))
    for k in range(len(path) - 1):
        D = path[k + 1] - path[k]; seg = (D, np.einsum("i,j->ij", D, D) / 2.0, np.einsum("i,j,k->ijk", D, D, D) / 6.0); S = _mul(S, seg)
    return np.concatenate([S[0].ravel(), S[1].ravel(), S[2].ravel()])


def levy_area(path2d: np.ndarray) -> float:
    """Aire de Lévy d'un chemin plan = (S^{12} - S^{21}) / 2 (niveau 2)."""
    s = signature(np.asarray(path2d, float)); d = 2; l2 = s[d: d + d * d].reshape(d, d); return float((l2[0, 1] - l2[1, 0]) / 2.0)
