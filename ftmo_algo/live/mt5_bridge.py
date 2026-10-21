"""Pont d'exécution MT5 (compte DÉMO uniquement). Les ordres partent du MÊME moteur (événements `open` de
Sim), avec stop et cible posés côté courtier dès l'entrée. Le passage au réel n'est JAMAIS automatique."""
from __future__ import annotations
import time
from collections import deque
from .gate import real_account_conditions


class BridgeError(RuntimeError):
    pass


def diagnose() -> tuple[bool, str]:
    """Indique précisément pourquoi la connexion MT5 est impossible, ou confirme qu'elle fonctionne."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return False, ("package MetaTrader5 non installé (pip install MetaTrader5 ; Windows uniquement, terminal MT5 "
                       "installé et ouvert sur la même machine). Environnement cloud/Linux : impossible.")
    if not mt5.initialize():
        return False, f"mt5.initialize() a échoué : {mt5.last_error()} (terminal fermé ? non connecté au courtier ?)"
    ai = mt5.account_info()
    if ai is None:
        return False, f"account_info() vide : {mt5.last_error()}"
    mode = {mt5.ACCOUNT_TRADE_MODE_DEMO: "DEMO", mt5.ACCOUNT_TRADE_MODE_REAL: "REEL",
            mt5.ACCOUNT_TRADE_MODE_CONTEST: "CONCOURS"}.get(ai.trade_mode, str(ai.trade_mode))
    return True, f"connecté : compte {ai.login} ({mode}) serveur {ai.server}, solde {ai.balance} {ai.currency}, levier 1:{ai.leverage}"


class MT5Bridge:
    def __init__(self, magic=26100, deviation=20, max_slip_mult=3.0, allow_real=False):
        import MetaTrader5 as mt5
        self.mt5, self.magic, self.deviation = mt5, magic, deviation
        if not mt5.initialize():
            raise BridgeError(f"initialize: {mt5.last_error()}")
        ai = mt5.account_info()
        self.demo = ai is not None and ai.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
        if not self.demo and not allow_real:
            raise BridgeError("compte NON démo : refus. Le passage au réel n'est jamais automatique "
                              "(voir live.gate.real_account_conditions).")
        self.fills = deque(maxlen=200)
        self.rejected = 0
        self.max_slip_mult = max_slip_mult

    def send_entry(self, sym, side, lots, sl, tp, expected_price, comment="ftmo_algo"):
        mt5 = self.mt5
        tick = mt5.symbol_info_tick(sym)
        price = tick.ask if side > 0 else tick.bid
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lots),
               "type": mt5.ORDER_TYPE_BUY if side > 0 else mt5.ORDER_TYPE_SELL, "price": price, "sl": float(sl),
               "tp": float(tp), "deviation": self.deviation, "magic": self.magic, "comment": comment[:30],
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
        res = mt5.order_send(req)
        ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        if not ok:
            self.rejected += 1
        ex = float(res.price) if ok else float("nan")
        self.fills.append({"t": time.time(), "sym": sym, "requested": price, "expected": expected_price, "executed": ex,
                           "slip": (ex - price) * side if ok else None, "ok": ok,
                           "retcode": None if res is None else res.retcode})
        return self.fills[-1]

    def close_all(self, sym=None):
        mt5 = self.mt5
        for p in mt5.positions_get(symbol=sym) or []:
            if p.magic != self.magic:
                continue
            tick = mt5.symbol_info_tick(p.symbol)
            side = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume, "type": side,
                            "position": p.ticket, "price": tick.bid if side == mt5.ORDER_TYPE_SELL else tick.ask,
                            "deviation": self.deviation, "magic": self.magic, "type_filling": mt5.ORDER_FILLING_IOC})

    def reconcile(self, paper_trades, backtest_expectancy=None):
        """Écart démo vs paper vs backtest : slippage réel moyen, rejets, taux d'exécution."""
        ok = [f for f in self.fills if f["ok"]]
        sl = [f["slip"] for f in ok if f["slip"] is not None]
        return {"orders": len(self.fills), "rejected": self.rejected, "mean_slippage": (sum(sl) / len(sl)) if sl else None,
                "paper_trades": len(paper_trades), "backtest_expectancy": backtest_expectancy}

    def abnormal(self, spec_slippage):
        sl = [abs(f["slip"]) for f in self.fills if f["ok"] and f["slip"] is not None][-10:]
        return len(sl) >= 5 and sum(sl) / len(sl) > self.max_slip_mult * max(spec_slippage, 1e-9)
