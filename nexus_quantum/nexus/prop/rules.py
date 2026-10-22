"""Regles FTMO 2-Step 100k (parametres) + gouverneur interne plus strict.

[HYPOTHESE] Valeurs issues de sources TIERCES (recherche web), pas du site FTMO
(inaccessible depuis cet environnement). A verifier sur ftmo.com avant tout usage.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FtmoRules:
    initial: float = 100_000.0
    target_p1: float = 0.10       # Challenge
    target_p2: float = 0.05       # Verification
    max_daily_loss: float = 0.05  # fraction du solde initial, mesure sur equity
    max_loss: float = 0.10        # statique, sous le solde initial
    min_days: int = 4


@dataclass(frozen=True)
class Governor:
    """Reduit l'exposition en approchant des limites; plus strict que FTMO."""
    soft_start: float = 0.98   # equity/initial: debut de la reduction lineaire
    floor: float = 0.93        # equity/initial: exposition nulle (marge de 3 pts vs 0.90)
    daily_stop: float = 0.03   # perte jour interne (marge de 2 pts vs 0.05)

    def __post_init__(self):
        r = FtmoRules()
        if not (1 - r.max_loss < self.floor < self.soft_start <= 1.0):
            raise ValueError("gouverneur doit rester strictement plus strict que la regle")
        if not 0 < self.daily_stop < r.max_daily_loss:
            raise ValueError("daily_stop doit etre < perte jour FTMO")

    def scale(self, equity_frac: float) -> float:
        if equity_frac >= self.soft_start:
            return 1.0
        if equity_frac <= self.floor:
            return 0.0
        return (equity_frac - self.floor) / (self.soft_start - self.floor)
