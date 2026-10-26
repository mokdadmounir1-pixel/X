"""Couche d'exécution : interface broker et paper trading.

Le trading sur terminal MT5 vit UNIQUEMENT dans quantbot/live (HardenedMT5Broker : approbation humaine, coupe-circuit,
journal préalable). Ce module ne contient aucun code d'envoi d'ordre.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from ..config import ExecutionConfig, FtmoConfig
from ..exceptions import ExecutionError, LiveTradingDisabledError
from ..logging_utils import get_logger
from ..risk.manager import TradePlan

log = get_logger("execution")


@dataclass
class Position:
    side: str
    entry: float
    size: float
    stop: float
    take_profit: float
    entry_time: Any
    entry_fee: float
    entry_idx: int = 0
    confidence: float = 0.0
    patterns: list[str] = field(default_factory=list)
    risk_amount: float = 0.0  # perte prévue si le stop est touché (taille plafonnée incluse)
    nominal_risk: float = 0.0  # risque visé avant plafonnement du levier

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1


@dataclass
class Trade:
    side: str
    entry_time: Any
    exit_time: Any
    entry: float
    exit: float
    size: float
    pnl: float
    reason: str
    confidence: float = 0.0
    patterns: list[str] = field(default_factory=list)
    bars_held: int = 0
    risk_amount: float = 0.0
    nominal_risk: float = 0.0
    stop: float = 0.0          # niveaux posés à l'ouverture (pour visualiser l'entrée / SL / TP de chaque trade)
    take_profit: float = 0.0

    @property
    def r_nominal(self) -> float:
        """Résultat en multiples du risque NOMINAL (equity x risk_per_trade) : borné par le levier, jamais « infini »."""
        return self.pnl / self.nominal_risk if self.nominal_risk > 0 else 0.0

    @property
    def r(self) -> float:
        """Résultat en multiples du risque initial (0 si le risque est inconnu)."""
        return self.pnl / self.risk_amount if self.risk_amount > 0 else 0.0


class Broker(ABC):
    @abstractmethod
    def open_position(self, plan: TradePlan, market_price: float, ts: Any, idx: int = 0) -> Position: ...

    @abstractmethod
    def close_position(self, price: float, ts: Any, reason: str, idx: int = 0, market: bool = True) -> Trade: ...

    @abstractmethod
    def equity(self, mark_price: Optional[float] = None) -> float: ...

    def balance(self) -> float:
        return self.equity()

    #: True si le broker gère lui-même SL/TP côté serveur (réel)
    manages_exits = False

    def sync(self, ts: Any, idx: int = 0) -> Optional[Trade]:
        """Détecte une clôture côté serveur (SL/TP) ; no-op en paper."""
        return None


class PaperBroker(Broker):
    def __init__(self, initial_equity: float, cfg: ExecutionConfig, cost_multiplier: float = 1.0) -> None:
        self.cash = float(initial_equity)
        self.fee_rate = cfg.fee_rate * cost_multiplier
        self.slippage = (cfg.slippage + cfg.spread / 2) * cost_multiplier
        self.position: Optional[Position] = None
        self.trades: list[Trade] = []

    def open_position(self, plan, market_price, ts, idx=0):
        if self.position is not None:
            raise ExecutionError("Position déjà ouverte")
        sign = 1 if plan.side == "long" else -1
        fill = market_price * (1 + sign * self.slippage)
        fee = self.fee_rate * fill * plan.size
        self.cash -= fee
        self.position = Position(plan.side, fill, plan.size, plan.stop, plan.take_profit, ts, fee, idx,
                                 plan.confidence, list(plan.patterns), plan.risk_amount, plan.nominal_risk)
        log.debug("OPEN %s %.4f @ %.4f", plan.side, plan.size, fill)
        return self.position

    def close_position(self, price, ts, reason, idx=0, market=True):
        pos = self.position
        if pos is None:
            raise ExecutionError("Aucune position à fermer")
        fill = price * (1 - pos.sign * self.slippage) if market else price  # TP = ordre limite
        gross = (fill - pos.entry) * pos.size * pos.sign
        exit_fee = self.fee_rate * fill * pos.size
        self.cash += gross - exit_fee
        trade = Trade(pos.side, pos.entry_time, ts, pos.entry, fill, pos.size,
                      gross - exit_fee - pos.entry_fee, reason, pos.confidence, pos.patterns,
                      idx - pos.entry_idx, pos.risk_amount, pos.nominal_risk, pos.stop, pos.take_profit)
        self.trades.append(trade)
        self.position = None
        log.debug("CLOSE %s @ %.4f (%s) pnl=%.2f", pos.side, fill, reason, trade.pnl)
        return trade

    def balance(self):
        return self.cash

    def equity(self, mark_price=None):
        pos = self.position
        if pos is None or mark_price is None:
            return self.cash
        return self.cash + (mark_price - pos.entry) * pos.size * pos.sign


def make_broker(initial_equity: float, cfg: ExecutionConfig, cost_multiplier: float = 1.0,
                ftmo: Optional[FtmoConfig] = None, mt5=None) -> Broker:
    if cfg.mode == "live":
        raise LiveTradingDisabledError("Le mode live ne passe plus par make_broker : utiliser quantbot.live (HardenedMT5Broker, "
                                       "approbation humaine, coupe-circuit)")
    return PaperBroker(initial_equity, cfg, cost_multiplier)
