"""Couche d'exécution : interface broker, paper trading, MetaTrader 5 réel.

Le trading réel (MT5Broker) exige un TRIPLE verrou : execution.mode="live",
execution.allow_live=true, variable d'environnement QUANTBOT_ALLOW_LIVE=1,
et ftmo.enabled=true (le garde-fou FTMO est obligatoire en réel).
MT5Broker n'a pu être validé que contre un faux module MT5 (tests) : à essayer
d'abord sur un compte d'essai FTMO / démo.
"""
from __future__ import annotations

import math
import os
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
                      idx - pos.entry_idx, pos.risk_amount, pos.nominal_risk)
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


class MT5Broker(Broker):
    """Ordres réels via le terminal MetaTrader 5 (compte FTMO ou démo).

    `mt5` est injectable (faux module en test). Un seul symbole, coté dans la
    devise du compte (ex. EURUSD sur compte USD) : pas de conversion de devise.
    SL/TP sont posés côté serveur à l'ouverture.
    """

    manages_exits = True

    def __init__(self, cfg: ExecutionConfig, ftmo: FtmoConfig, mt5=None) -> None:
        if cfg.mode != "live" or not cfg.allow_live or os.environ.get("QUANTBOT_ALLOW_LIVE") != "1":
            raise LiveTradingDisabledError(
                "Trading réel désactivé : execution.mode=live, execution.allow_live=true "
                "ET QUANTBOT_ALLOW_LIVE=1 requis")
        if not ftmo.enabled:
            raise LiveTradingDisabledError("Le garde-fou FTMO (ftmo.enabled) est obligatoire en réel")
        if mt5 is None:
            try:
                import MetaTrader5 as mt5  # type: ignore
            except ImportError as exc:
                raise ExecutionError("Paquet MetaTrader5 indisponible (Windows + terminal MT5 requis)") from exc
        self.mt5, self.cfg = mt5, cfg
        self.symbol = cfg.mt5_symbol
        self.position: Optional[Position] = None
        self.trades: list[Trade] = []
        self._ticket: Optional[int] = None
        if not mt5.initialize():
            raise ExecutionError(f"Initialisation MT5 impossible : {mt5.last_error()}")
        acct = mt5.account_info()
        if acct is None:
            raise ExecutionError("Compte MT5 introuvable (terminal connecté ?)")
        if ftmo.expected_login is not None and acct.login != ftmo.expected_login:
            raise ExecutionError(f"Compte MT5 {acct.login} différent du compte attendu {ftmo.expected_login}")
        info = mt5.symbol_info(self.symbol)
        if info is None or not mt5.symbol_select(self.symbol, True):
            raise ExecutionError(f"Symbole MT5 indisponible : {self.symbol}")
        if getattr(info, "currency_profit", acct.currency) != acct.currency:
            raise ExecutionError(
                f"{self.symbol} est coté en {info.currency_profit}, compte en {acct.currency} : "
                "conversion de devise non supportée")
        log.warning("MT5 RÉEL actif : compte %s (%s) symbole %s", acct.login, getattr(acct, "server", "?"), self.symbol)

    # --- état du compte
    def balance(self) -> float:
        return float(self.mt5.account_info().balance)

    def equity(self, mark_price=None) -> float:
        return float(self.mt5.account_info().equity)

    def _lots(self, units: float) -> float:
        info = self.mt5.symbol_info(self.symbol)
        step = info.volume_step or 0.01
        lots = math.floor(units / info.trade_contract_size / step + 1e-9) * step
        lots = round(min(lots, info.volume_max), 8)
        if lots < info.volume_min:
            raise ExecutionError(f"Taille {units:.0f} u. < volume minimum ({info.volume_min} lot)")
        return lots

    def _find_ticket(self) -> Optional[int]:
        for p in self.mt5.positions_get(symbol=self.symbol) or ():
            if p.magic == self.cfg.mt5_magic:
                return int(p.ticket)
        return None

    def open_position(self, plan, market_price, ts, idx=0):
        if self.position is not None:
            raise ExecutionError("Position déjà ouverte")
        mt5 = self.mt5
        lots = self._lots(plan.size)
        tick = mt5.symbol_info_tick(self.symbol)
        long = plan.side == "long"
        price = tick.ask if long else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": lots,
            "type": mt5.ORDER_TYPE_BUY if long else mt5.ORDER_TYPE_SELL, "price": price,
            "sl": float(plan.stop), "tp": float(plan.take_profit), "deviation": self.cfg.mt5_deviation_points,
            "magic": self.cfg.mt5_magic, "comment": "quantbot", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise ExecutionError(f"order_send refusé : {getattr(result, 'retcode', None)} "
                                 f"{getattr(result, 'comment', mt5.last_error())}")
        contract = mt5.symbol_info(self.symbol).trade_contract_size
        self._ticket = self._find_ticket()
        self.position = Position(plan.side, float(result.price or price), lots * contract, plan.stop,
                                 plan.take_profit, ts, 0.0, idx, plan.confidence, list(plan.patterns),
                                 plan.risk_amount, plan.nominal_risk)
        log.warning("ORDRE RÉEL %s %.2f lot @ %.5f SL=%.5f TP=%.5f", plan.side, lots, self.position.entry,
                    plan.stop, plan.take_profit)
        return self.position

    def _deals_trade(self, ts, reason, idx) -> Trade:
        pos = self.position
        deals = list(self.mt5.history_deals_get(position=self._ticket) or ()) if self._ticket else []
        pnl = sum(getattr(d, "profit", 0.0) + getattr(d, "commission", 0.0) + getattr(d, "swap", 0.0)
                  + getattr(d, "fee", 0.0) for d in deals)
        exit_price = float(deals[-1].price) if deals else pos.entry
        trade = Trade(pos.side, pos.entry_time, ts, pos.entry, exit_price, pos.size, float(pnl), reason,
                      pos.confidence, pos.patterns, idx - pos.entry_idx, pos.risk_amount, pos.nominal_risk)
        self.trades.append(trade)
        self.position, self._ticket = None, None
        return trade

    def sync(self, ts, idx=0):
        if self.position is None:
            return None
        if self._ticket is None:
            self._ticket = self._find_ticket()
        if self._ticket is not None and self._find_ticket() == self._ticket:
            return None  # toujours ouverte
        return self._deals_trade(ts, "server_exit", idx)

    def close_position(self, price, ts, reason, idx=0, market=True):
        pos = self.position
        if pos is None:
            raise ExecutionError("Aucune position à fermer")
        mt5 = self.mt5
        if self._ticket is None:
            self._ticket = self._find_ticket()
        if self._ticket is None:  # déjà clôturée côté serveur
            return self._deals_trade(ts, reason, idx)
        tick = mt5.symbol_info_tick(self.symbol)
        long = pos.side == "long"
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "position": self._ticket,
            "volume": self._lots(pos.size), "type": mt5.ORDER_TYPE_SELL if long else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if long else tick.ask, "deviation": self.cfg.mt5_deviation_points,
            "magic": self.cfg.mt5_magic, "comment": f"quantbot:{reason}"[:30],
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise ExecutionError(f"Clôture refusée : {getattr(result, 'retcode', None)} "
                                 f"{getattr(result, 'comment', mt5.last_error())}")
        log.warning("CLÔTURE RÉELLE %s (%s)", pos.side, reason)
        return self._deals_trade(ts, reason, idx)


def make_broker(initial_equity: float, cfg: ExecutionConfig, cost_multiplier: float = 1.0,
                ftmo: Optional[FtmoConfig] = None, mt5=None) -> Broker:
    if cfg.mode == "live":
        return MT5Broker(cfg, ftmo or FtmoConfig(), mt5)
    return PaperBroker(initial_equity, cfg, cost_multiplier)
