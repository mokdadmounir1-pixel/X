"""Modele de couts par aller-retour, avec stress. Tous les tarifs sont des ENTREES.

Aucun tarif de broker/bourse n'est code en dur: ils changent et doivent etre
verifies sur les grilles tarifaires en vigueur avant toute conclusion [HYPOTHESE].
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str
    tick_size: float
    tick_value: float   # monnaie par tick et par contrat


@dataclass(frozen=True)
class CostModel:
    commission_per_side: float      # par contrat
    exchange_fee_per_side: float    # par contrat (net des rebates eventuels)
    spread_ticks: float             # spread moyen en ticks (paye si on traverse)
    slippage_ticks_per_side: float  # glissement moyen par cote
    crosses_spread: bool = True     # False = entree/sortie passives (mais adverse selection)

    def round_trip(self, inst: Instrument, qty: float = 1.0, stress: float = 1.0) -> float:
        fees = 2 * (self.commission_per_side + self.exchange_fee_per_side)
        ticks = (self.spread_ticks if self.crosses_spread else 0.0) \
            + 2 * self.slippage_ticks_per_side
        return stress * qty * (fees + ticks * inst.tick_value)

    def breakeven_ticks(self, inst: Instrument, stress: float = 1.0) -> float:
        """Edge brut minimal (en ticks/contrat/aller-retour) pour esperance nulle."""
        return self.round_trip(inst, 1.0, stress) / inst.tick_value
