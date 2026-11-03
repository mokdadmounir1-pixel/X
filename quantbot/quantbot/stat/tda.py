"""Porte topologique (TDA) de SIG-TDA : homologie persistante H1 d'un nuage de points (ripser) et norme L1 du paysage de persistance.

||Lambda||_1 = SOMME_i ((d_i - b_i) / 2)^2 (forme fermée du cahier, somme des aires des tentes). Sans la bibliothèque `ripser` : renvoie None (la porte est INCONNUE et la stratégie ne prend AUCUN trade : une porte de sécurité absente n'est jamais supposée ouverte).
"""
from __future__ import annotations

import numpy as np

try:
    from ripser import ripser as _ripser
except Exception:       # bibliothèque absente
    _ripser = None


def available() -> bool:
    return _ripser is not None


def landscape_l1(points: np.ndarray) -> float | None:
    if _ripser is None:
        return None
    pts = np.asarray(points, float)
    if len(pts) < 5 or not np.isfinite(pts).all():
        return None
    h1 = _ripser(pts, maxdim=1)["dgms"][1]
    if len(h1) == 0:
        return 0.0
    life = h1[:, 1] - h1[:, 0]; life = life[np.isfinite(life)]
    return float(np.sum((life / 2.0) ** 2))
