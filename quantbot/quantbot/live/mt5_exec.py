"""Broker MT5 DURCI pour le bot en direct.

Règles : coupe-circuit vérifié avant toute entrée ; intention écrite AVANT envoi (write-ahead) ; `order_check` obligatoire ;
mode de remplissage détecté ; stop ET cible posés à l'envoi ; retry borné SEULEMENT pour requote/prix changé (même intention) ;
réponse ambiguë => état INCONNU + coupe-circuit + AUCUN renvoi ; compte non démo refusé sans triple autorisation.
"""
from __future__ import annotations

import math
import os
from typing import Any, Optional

from ..config import ExecutionConfig, FtmoConfig
from ..exceptions import ExecutionError, LiveTradingDisabledError
from ..execution.broker import Broker, Position, Trade
from ..logging_utils import get_logger
from ..risk.manager import TradePlan
from .killswitch import KillSwitch
from .state import StateStore

log = get_logger("live.mt5_exec")


class HardenedMT5Broker(Broker):
    manages_exits = True

    def __init__(self, execution: ExecutionConfig, ftmo: FtmoConfig, mt5: Any, state: StateStore, kill: KillSwitch,
                 strategy: str = "", allowed_servers: tuple = (), allow_real: bool = False, max_retries: int = 2) -> None:
        self.cfg, self.mt5, self.state, self.kill, self.strategy, self.max_retries = execution, mt5, state, kill, strategy, max_retries
        self.symbol = execution.mt5_symbol
        self.position: Optional[Position] = None
        self.trades: list[Trade] = []
        self._ticket: Optional[int] = None
        if not mt5.initialize():
            raise ExecutionError(f"Initialisation MT5 impossible : {mt5.last_error()}")
        acct = mt5.account_info()
        if acct is None:
            raise ExecutionError("Compte MT5 introuvable (terminal connecté ?)")
        demo = acct.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
        if not demo and not (allow_real and execution.allow_live and ftmo.enabled and os.environ.get("QUANTBOT_ALLOW_LIVE") == "1"):
            raise LiveTradingDisabledError("Compte NON démo : refus (autorisation réelle = allow_real + allow_live + ftmo.enabled + QUANTBOT_ALLOW_LIVE=1)")
        if allowed_servers and acct.server not in allowed_servers:
            raise ExecutionError(f"Serveur « {acct.server} » hors liste blanche {list(allowed_servers)}")
        if ftmo.expected_login is not None and acct.login != ftmo.expected_login:
            raise ExecutionError(f"Compte {acct.login} différent du compte attendu")
        info = mt5.symbol_info(self.symbol)
        if info is None or not mt5.symbol_select(self.symbol, True):
            raise ExecutionError(f"Symbole MT5 indisponible : {self.symbol}")
        if getattr(info, "currency_profit", acct.currency) != acct.currency:
            raise ExecutionError(f"{self.symbol} coté en {info.currency_profit}, compte en {acct.currency} : conversion non supportée")
        self.demo = demo
        state.log("INFO", "broker_init", f"compte={acct.login} serveur={acct.server} démo={demo}")

    # --- état du compte --------------------------------------------------------------------------
    def balance(self) -> float: return float(self.mt5.account_info().balance)
    def equity(self, mark_price=None) -> float: return float(self.mt5.account_info().equity)

    # --- utilitaires ---------------------------------------------------------------------------------
    def _guard(self) -> None:
        reasons = self.kill.reasons()
        if reasons:
            raise ExecutionError("coupe-circuit actif : " + "; ".join(reasons))

    def _filling(self) -> int:
        """Mode de remplissage supporté par le symbole (jamais IOC en dur)."""
        m, flags = self.mt5, getattr(self.mt5.symbol_info(self.symbol), "filling_mode", 0)
        if flags & m.SYMBOL_FILLING_IOC:
            return m.ORDER_FILLING_IOC
        if flags & m.SYMBOL_FILLING_FOK:
            return m.ORDER_FILLING_FOK
        return m.ORDER_FILLING_RETURN

    def _lots(self, units: float) -> float:
        info = self.mt5.symbol_info(self.symbol)
        step = info.volume_step or 0.01
        lots = round(min(math.floor(units / info.trade_contract_size / step + 1e-9) * step, info.volume_max), 8)
        if lots < info.volume_min:
            raise ExecutionError(f"Taille {units:.2f} u. < volume minimum ({info.volume_min} lot)")
        return lots

    def _find(self, comment: str) -> Optional[Any]:
        for p in self.mt5.positions_get(symbol=self.symbol) or ():
            if p.magic == self.cfg.mt5_magic and getattr(p, "comment", "") == comment:
                return p
        return None

    def _codes(self):
        m = self.mt5
        return (m.TRADE_RETCODE_DONE, {m.TRADE_RETCODE_REQUOTE, m.TRADE_RETCODE_PRICE_CHANGED},
                {m.TRADE_RETCODE_TIMEOUT, m.TRADE_RETCODE_CONNECTION})

    def _ambiguous(self, iid: str, why: str) -> None:
        self.state.mark(iid, "UNKNOWN", why)
        self.kill.trigger(f"réponse ambiguë (intention {iid}) : {why}")

    # --- ouverture ------------------------------------------------------------------------------------
    def open_position(self, plan: TradePlan, market_price: float, ts: Any, idx: int = 0) -> Position:
        self._guard()
        if self.position is not None:
            raise ExecutionError("Position déjà ouverte")
        if not (plan.stop > 0 and plan.take_profit > 0):
            raise ExecutionError("Stop et cible obligatoires")
        m = self.mt5
        iid = self.state.new_intent("OPEN", plan.side, {k: getattr(plan, k) for k in ("side", "entry", "stop", "take_profit", "size", "risk_amount")}, self.strategy)
        done, transient, ambiguous = self._codes()
        try:
            lots = self._lots(plan.size)
        except ExecutionError as exc:
            self.state.mark(iid, "FAILED", str(exc)); raise
        digits = getattr(m.symbol_info(self.symbol), "digits", 5)
        comment = f"qb:{iid}"
        for attempt in range(self.max_retries + 1):
            tick = m.symbol_info_tick(self.symbol)
            if tick is None:
                self.state.mark(iid, "FAILED", "pas de cotation"); raise ExecutionError("Pas de cotation")
            long = plan.side == "long"
            req = {"action": m.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": lots,
                   "type": m.ORDER_TYPE_BUY if long else m.ORDER_TYPE_SELL, "price": float(tick.ask if long else tick.bid),
                   "sl": round(float(plan.stop), digits), "tp": round(float(plan.take_profit), digits),
                   "deviation": self.cfg.mt5_deviation_points, "magic": self.cfg.mt5_magic, "comment": comment,
                   "type_time": m.ORDER_TIME_GTC, "type_filling": self._filling()}
            chk = m.order_check(req)
            if chk is None or chk.retcode not in (0, done):
                self.state.mark(iid, "REFUSED", f"order_check: {getattr(chk, 'retcode', None)} {getattr(chk, 'comment', '')}")
                raise ExecutionError(f"order_check refusé : {getattr(chk, 'retcode', None)}")
            self.state.mark(iid, "SENT", f"tentative {attempt}")
            res = m.order_send(req)
            if res is None or res.retcode in ambiguous:
                self._ambiguous(iid, "réponse absente/ambiguë à l'envoi")
                found = self._find(comment)  # le serveur a peut-être exécuté : on le vérifie, on ne renvoie JAMAIS
                if found is None:
                    raise ExecutionError("État INCONNU : ordre peut-être exécuté ; coupe-circuit actif, réconciliation humaine requise")
                self.state.mark(iid, "CONFIRMED", "résolu par réconciliation", int(found.ticket))
                self.state.log("WARNING", "ambiguite_resolue", "position retrouvée ; le coupe-circuit RESTE actif (levée humaine uniquement)")
                return self._adopt(plan, float(found.price_open), lots, ts, idx, int(found.ticket))
            if res.retcode == done:
                self.state.mark(iid, "CONFIRMED", "exécuté", int(getattr(res, "order", 0)) or None)
                pos = self._find(comment)
                ticket = int(pos.ticket) if pos is not None else int(getattr(res, "order", 0) or 0)
                return self._adopt(plan, float(res.price or req["price"]), lots, ts, idx, ticket)
            if res.retcode in transient and attempt < self.max_retries:
                self.state.log("WARNING", "retry", f"retcode {res.retcode}, intention {iid}")
                continue
            self.state.mark(iid, "REFUSED", f"retcode {res.retcode} {getattr(res, 'comment', '')}")
            raise ExecutionError(f"order_send refusé : {res.retcode}")
        raise ExecutionError("tentatives épuisées")

    def _adopt(self, plan: TradePlan, price: float, lots: float, ts: Any, idx: int, ticket: int) -> Position:
        contract = self.mt5.symbol_info(self.symbol).trade_contract_size
        self._ticket = ticket
        self.position = Position(plan.side, price, lots * contract, plan.stop, plan.take_profit, ts, 0.0, idx, plan.confidence,
                                 list(plan.patterns), plan.risk_amount, plan.nominal_risk)
        log.warning("POSITION %s %.2f lot @ %.5f SL=%.5f TP=%.5f (ticket %s)", plan.side, lots, price, plan.stop, plan.take_profit, ticket)
        return self.position

    # --- sorties -----------------------------------------------------------------------------------------
    def _trade_from_deals(self, ts: Any, reason: str, idx: int) -> Trade:
        pos = self.position
        deals = list(self.mt5.history_deals_get(position=self._ticket) or ()) if self._ticket else []
        pnl = sum(getattr(d, "profit", 0.0) + getattr(d, "commission", 0.0) + getattr(d, "swap", 0.0) + getattr(d, "fee", 0.0) for d in deals)
        exit_price = float(deals[-1].price) if deals else pos.entry
        t = Trade(pos.side, pos.entry_time, ts, pos.entry, exit_price, pos.size, float(pnl), reason, pos.confidence, pos.patterns,
                  idx - pos.entry_idx, pos.risk_amount, pos.nominal_risk)
        self.trades.append(t)
        self.position, self._ticket = None, None
        return t

    def sync(self, ts: Any, idx: int = 0) -> Optional[Trade]:
        if self.position is None:
            return None
        still = any(int(p.ticket) == self._ticket for p in (self.mt5.positions_get(symbol=self.symbol) or ()))
        return None if still else self._trade_from_deals(ts, "server_exit", idx)

    def close_position(self, price: float, ts: Any, reason: str, idx: int = 0, market: bool = True) -> Trade:
        """Les clôtures restent permises même coupe-circuit actif (sortir est toujours plus sûr que rester)."""
        pos = self.position
        if pos is None:
            raise ExecutionError("Aucune position à fermer")
        m = self.mt5
        still = [p for p in (m.positions_get(symbol=self.symbol) or ()) if int(p.ticket) == self._ticket]
        if not still:
            return self._trade_from_deals(ts, reason, idx)
        iid = self.state.new_intent("CLOSE", pos.side, {"ticket": self._ticket, "reason": reason}, self.strategy)
        done, _transient, ambiguous = self._codes()
        tick = m.symbol_info_tick(self.symbol)
        long = pos.side == "long"
        req = {"action": m.TRADE_ACTION_DEAL, "symbol": self.symbol, "position": self._ticket, "volume": float(still[0].volume),
               "type": m.ORDER_TYPE_SELL if long else m.ORDER_TYPE_BUY, "price": float(tick.bid if long else tick.ask),
               "deviation": self.cfg.mt5_deviation_points, "magic": self.cfg.mt5_magic, "comment": f"qb:{iid}",
               "type_time": m.ORDER_TIME_GTC, "type_filling": self._filling()}
        chk = m.order_check(req)
        if chk is None or chk.retcode not in (0, done):
            self.state.mark(iid, "REFUSED", f"order_check: {getattr(chk, 'retcode', None)}")
            raise ExecutionError(f"Clôture refusée par order_check : {getattr(chk, 'retcode', None)}")
        self.state.mark(iid, "SENT")
        res = m.order_send(req)
        if res is None or res.retcode in ambiguous:
            self._ambiguous(iid, "réponse ambiguë à la clôture")
            if not any(int(p.ticket) == self._ticket for p in (m.positions_get(symbol=self.symbol) or ())):
                self.state.mark(iid, "CONFIRMED", "clôture constatée par réconciliation")
                return self._trade_from_deals(ts, reason, idx)
            raise ExecutionError("État INCONNU à la clôture ; coupe-circuit actif")
        if res.retcode != done:
            self.state.mark(iid, "REFUSED", f"retcode {res.retcode}")
            raise ExecutionError(f"Clôture refusée : {res.retcode}")
        self.state.mark(iid, "CONFIRMED", reason)
        return self._trade_from_deals(ts, reason, idx)

    # --- reprise -------------------------------------------------------------------------------------------
    def restore(self, engine_n: int) -> Optional[Position]:
        """Au démarrage : adopte une position portant notre magic ET connue de l'état ; toute autre = orpheline => coupe-circuit."""
        ours = [p for p in (self.mt5.positions_get(symbol=self.symbol) or ()) if p.magic == self.cfg.mt5_magic]
        if not ours:
            return None
        known = self.state.known_tickets()
        orphans = [p for p in ours if int(p.ticket) not in known]
        if orphans or len(ours) > 1:
            self.kill.trigger(f"position(s) orpheline(s) ou multiples au démarrage : {[int(p.ticket) for p in ours]}")
            raise ExecutionError("Position orpheline/multiple : coupe-circuit déclenché, intervention humaine requise")
        p = ours[0]
        contract = self.mt5.symbol_info(self.symbol).trade_contract_size
        self._ticket = int(p.ticket)
        side = "long" if p.type == self.mt5.POSITION_TYPE_BUY else "short"
        self.position = Position(side, float(p.price_open), float(p.volume) * contract, float(p.sl), float(p.tp), None, 0.0, engine_n, 0.0, [], 0.0, 0.0)
        self.state.log("WARNING", "restore", f"position {self._ticket} adoptée (la durée de détention repart de zéro)")
        return self.position
