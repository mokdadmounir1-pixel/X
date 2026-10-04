"""Rejet detaille obligatoire : plus aucun ecartement generique.

Chaque rejet porte un motif exact, une preuve et un indice de confiance, ecrits en base (table `rejection`,
immuable) ET affiches dans le journal des appels.

CONVENTION DE L'INDICE DE CONFIANCE (ce n'est PAS une probabilite calibree) :
  regle_deterministe = 1.00  (controle exact : champ absent, doublon, citation introuvable, opposition en base)
  decision_humaine   = 1.00  (le fondateur a decide)
  heuristique        <= 0.90 (seuil sur un score a regles)
  modele             = confiance declaree par le modele, plafonnee a 0.90 (jamais verifiee)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

STAGES = ("sourcing", "analyse", "redaction", "revue", "decision_fondateur", "closing", "pipeline")
BASES = ("regle_deterministe", "heuristique", "modele", "decision_humaine")


@dataclass(frozen=True)
class RejectionDetail:
    stage: str
    agent: str
    motif_exact: str
    preuve_source: dict
    indice_confiance: float
    base_confiance: str

    def __post_init__(self):
        if self.stage not in STAGES:
            raise ValueError(f"stage inconnu: {self.stage}")
        if not self.agent or len(self.motif_exact.strip()) < 8:
            raise ValueError("rejection_detail: motif_exact precis obligatoire")
        if not isinstance(self.preuve_source, dict) or "type" not in self.preuve_source:
            raise ValueError("rejection_detail: preuve_source obligatoire (avec un 'type')")
        if not 0.0 <= float(self.indice_confiance) <= 1.0:
            raise ValueError("rejection_detail: indice_confiance hors [0,1]")
        if self.base_confiance not in BASES:
            raise ValueError(f"base_confiance inconnue: {self.base_confiance}")
        if self.base_confiance in ("heuristique", "modele") and self.indice_confiance > 0.90:
            raise ValueError("une heuristique ou un modele ne peut pas annoncer plus de 0.90")

    def as_dict(self) -> dict:
        return asdict(self)

    def short(self) -> str:
        return f"{self.motif_exact} [preuve: {self.preuve_source.get('type')}; confiance {self.indice_confiance:.2f} ({self.base_confiance})]"


def deterministic(stage, agent, motif, preuve) -> RejectionDetail:
    return RejectionDetail(stage, agent, motif, preuve, 1.0, "regle_deterministe")


def heuristic(stage, agent, motif, preuve, confidence) -> RejectionDetail:
    return RejectionDetail(stage, agent, motif, preuve, min(0.90, float(confidence)), "heuristique")


def human(stage, agent, motif, preuve) -> RejectionDetail:
    return RejectionDetail(stage, agent, motif, preuve, 1.0, "decision_humaine")


def emit_rejection(trace, db, src: str, dst: str, lead_ref: str, d: RejectionDetail, kind="rejet"):
    """Ecrit le rejet en base (avec preuve) et l'affiche dans le journal avec sa raison precise."""
    res = db.record_rejection(lead_ref, d.stage, d.agent, d.motif_exact, d.preuve_source, d.indice_confiance, d.base_confiance)
    if not res.ok:     # un rejet que la base refuse d'enregistrer est un BUG de l'agent, jamais un cas a ignorer
        raise RuntimeError(f"rejet non enregistrable ({res.code}) : {d}")
    trace.emit(src, dst, kind, f"écarté — {d.motif_exact}", ok=False, code=d.stage,
               rejection_detail=d.as_dict(), rejection_id=res.id)
    return res
