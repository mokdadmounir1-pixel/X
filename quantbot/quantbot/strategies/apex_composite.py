"""Score composite Ω des piliers DISPONIBLES, sans jamais remplacer une donnée absente par une valeur.

Le composite demandé (somme pondérée, I_ofi dans [-1, 1]) laisserait un pilier fort compenser un pilier nul. On utilise donc une moyenne géométrique pondérée de scores
dans [0, 1] (un pilier à 0 annule le setup) ; un pilier directionnel signé (OFI, télémétrie) est converti : max(0, signe_du_trade x valeur).
Piliers sans donnée réelle (GEX sans chaîne d'options, OFI sans tailles de carnet...) sont EXCLUS et listés dans `missing` ; les poids sont renormalisés sur les piliers présents.
"""
from __future__ import annotations

import math

WEIGHTS = {"S": 0.30, "G": 0.25, "I": 0.25, "T": 0.20}


def composite(scores: dict, direction: int, weights: dict | None = None) -> dict:
    """scores : {"S": [0,1], "G": [0,1] | None, "I": [-1,1] | None, "T": [-1,1] | None} ; direction : +1 achat, -1 vente."""
    w = {**WEIGHTS, **(weights or {})}; use, missing = {}, []
    for k in w:
        v = scores.get(k)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            missing.append(k); continue
        use[k] = max(0.0, direction * v) if k in ("I", "T") else max(0.0, min(1.0, v))
    if not use:
        return {"omega": 0.0, "used": [], "missing": missing}
    tot = sum(w[k] for k in use)
    return {"omega": float(math.exp(sum(w[k] / tot * math.log(max(use[k], 1e-12)) for k in use))) if all(v > 0 for v in use.values()) else 0.0, "used": sorted(use), "missing": missing}
