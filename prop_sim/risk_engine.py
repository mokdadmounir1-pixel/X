"""Moteur de risque déterministe. Il peut bloquer un signal ; rien ici ne
peut être modifié par un agent/LLM à l'exécution : les limites sont un
dataclass figé, dont l'empreinte est enregistrée dans le livre virtuel."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

HARD_CAP_RISK_PER_TRADE_PCT = 0.60  # plafond existant, non négociable


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade_pct: float = 0.25        # risque demandé par défaut (pas le plafond)
    max_risk_per_trade_pct: float = 0.60
    max_open_risk_pct: float = 1.50         # somme des risques au stop des positions ouvertes
    max_currency_net_risk_pct: float = 1.00  # exposition nette par devise (signée)
    max_concurrent: int = 3
    # Tampons internes, plus stricts que les limites FTMO (5 % jour / 10 % total)
    internal_daily_loss_pct: float = 3.0
    internal_total_loss_pct: float = 6.0
    max_signals_per_day: int = 10

    def __post_init__(self):
        if not 0 < self.max_risk_per_trade_pct <= HARD_CAP_RISK_PER_TRADE_PCT:
            raise ValueError("max_risk_per_trade_pct must be in (0, 0.60]")
        if not 0 < self.risk_per_trade_pct <= self.max_risk_per_trade_pct:
            raise ValueError("risk_per_trade_pct must be in (0, max_risk_per_trade_pct]")

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class OpenRisk:
    pair: str
    direction: str
    risk_pct: float


@dataclass(frozen=True)
class Decision:
    approved: bool
    reasons: tuple = ()


def currency_exposure(pair: str, direction: str, risk_pct: float) -> dict:
    s = 1 if direction == "long" else -1
    return {pair[:3]: s * risk_pct, pair[3:]: -s * risk_pct}


class RiskEngine:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def evaluate(self, *, pair, direction, risk_pct, equity, day_start_equity,
                 initial_balance, open_risks, signals_today) -> Decision:
        L, why = self.limits, []
        if risk_pct <= 0 or risk_pct > L.max_risk_per_trade_pct + 1e-12:
            why.append("risk_per_trade_above_cap")
        if any(o.pair == pair for o in open_risks):
            why.append("pair_already_open")
        if len(open_risks) >= L.max_concurrent:
            why.append("concurrent_limit")
        if signals_today >= L.max_signals_per_day:
            why.append("daily_signal_cap")

        open_total = sum(o.risk_pct for o in open_risks)
        if open_total + risk_pct > L.max_open_risk_pct + 1e-12:
            why.append("cumulative_open_risk")

        net: dict = {}
        for o in open_risks:
            for c, v in currency_exposure(o.pair, o.direction, o.risk_pct).items():
                net[c] = net.get(c, 0.0) + v
        for c, v in currency_exposure(pair, direction, risk_pct).items():
            if abs(net.get(c, 0.0) + v) > L.max_currency_net_risk_pct + 1e-12:
                why.append(f"correlated_exposure_{c}")

        # Flottant inclus : equity, pas balance.
        day_loss = max(0.0, (day_start_equity - equity) / initial_balance * 100)
        if day_loss + open_total + risk_pct > L.internal_daily_loss_pct:
            why.append("daily_loss_budget")
        total_loss = max(0.0, (initial_balance - equity) / initial_balance * 100)
        if total_loss + open_total + risk_pct > L.internal_total_loss_pct:
            why.append("total_loss_budget")
        return Decision(not why, tuple(why))
