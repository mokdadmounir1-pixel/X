"""Faux terminal MetaTrader 5 pour tester le bot en direct SANS terminal. Comportements scriptables : refus, requote, timeout (None)."""
from types import SimpleNamespace as NS

import numpy as np


class FakeMT5Live:
    TIMEFRAME_M1, TIMEFRAME_M15, TIMEFRAME_H1 = 1, 15, 16385
    TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TIME_GTC = 1, 0, 1, 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    # NB : le module réel (5.0.6180) n'expose PAS SYMBOL_FILLING_FOK/IOC (constaté par C1) : le faux ne les fournit plus.
    TRADE_RETCODE_DONE, TRADE_RETCODE_REQUOTE, TRADE_RETCODE_PRICE_CHANGED = 10009, 10004, 10020
    TRADE_RETCODE_TIMEOUT, TRADE_RETCODE_REJECT, TRADE_RETCODE_NO_MONEY, TRADE_RETCODE_CONNECTION = 10012, 10006, 10019, 10031
    TRADE_RETCODE_DONE_PARTIAL = 10010
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST, ACCOUNT_TRADE_MODE_REAL = 0, 1, 2
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1

    def __init__(self, n_bars=400, demo=True, login=1234, server="MetaQuotes-Demo", filling_mode=2, seed=0, price0=2000.0,
                 volume_min=0.01, trade_stops_level=0, account_currency="USD", trade_exemode=1, usd_per_unit=1.0):
        rng = np.random.default_rng(seed)
        import calendar
        # la barre d'indice n_bars tombe un MARDI 11 h UTC (horloge courtier +3 h) : hors fenêtre de week-end
        self.t0 = calendar.timegm((2024, 6, 11, 14, 0, 0)) - 900 * n_bars
        px = price0 + np.cumsum(rng.normal(0, 0.4, n_bars + 1))
        self.bars = []
        for i in range(n_bars + 1):  # le DERNIER élément est la barre en formation
            o = px[i - 1] if i else price0
            c = px[i]
            self.bars.append({"time": self.t0 + 900 * i, "open": float(o), "high": float(max(o, c) + .2), "low": float(min(o, c) - .2),
                              "close": float(c), "tick_volume": 100 + i, "spread": 12, "real_volume": 0})
        self.acct = NS(login=login, currency=account_currency, server=server, balance=100_000.0, equity=100_000.0,
                       trade_mode=self.ACCOUNT_TRADE_MODE_DEMO if demo else self.ACCOUNT_TRADE_MODE_REAL)
        self.info = NS(currency_profit="USD", trade_contract_size=100, volume_step=0.01, volume_min=volume_min, volume_max=50.0,
                       filling_mode=filling_mode, trade_exemode=trade_exemode, digits=2, point=0.01, trade_stops_level=trade_stops_level)
        self.checked, self.sent, self.positions, self.deals = [], [], [], []
        self.check_script, self.send_script = [], []   # retcodes (int), "NONE" (réponse None), ou callable(req)
        self._ticket = 1000
        self.initialized = False
        self.positions_error = False   # positions_get -> None + erreur réelle
        self.partial_fraction = None   # exécution partielle (DONE_PARTIAL) à la fraction donnée
        self.account_per_usd = 1.0     # EUR par USD pour order_calc_profit

    # --- cycle de vie
    def initialize(self): self.initialized = True; return True
    def shutdown(self): self.initialized = False
    def last_error(self): return (-1, "erreur") if self.positions_error else (1, "Success")
    def account_info(self): return self.acct
    def symbol_info(self, s): return self.info
    def symbol_select(self, s, e): return True

    def symbol_info_tick(self, s):
        c = self.bars[-1]["close"]
        return NS(bid=c, ask=c + 0.12)

    def advance(self, k=1):
        """k nouvelles barres : l'ancienne barre en formation devient close."""
        for _ in range(k):
            last = self.bars[-1]
            c = last["close"] + (0.3 if len(self.bars) % 2 else -0.2)
            self.bars.append({"time": last["time"] + 900, "open": last["close"], "high": max(last["close"], c) + .2,
                              "low": min(last["close"], c) - .2, "close": c, "tick_volume": last["tick_volume"] + 1, "spread": 12, "real_volume": 0})

    def copy_rates_from_pos(self, sym, tf, start, n):
        end = len(self.bars) - start
        rows = self.bars[max(0, end - n):end]
        # comme le VRAI module : ndarray structuré (champs nommés), pas une liste de dicts (constaté par C2)
        dt = [("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
              ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")]
        return np.array([tuple(r[k] for k, _ in dt) for r in rows], dtype=dt)

    def copy_rates_range(self, sym, tf, d0, d1):
        import calendar
        e0, e1 = calendar.timegm(d0.utctimetuple()), calendar.timegm(d1.utctimetuple())
        rows = [b for b in self.bars if e0 <= b["time"] <= e1]
        if not rows:
            return None if getattr(self, "range_error", False) else np.array([], dtype=[("time", "<i8")])
        dt = [("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
              ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")]
        return np.array([tuple(r[k] for k, _ in dt) for r in rows], dtype=dt)

    # --- ordres
    def positions_get(self, symbol=None):
        if self.positions_error:
            return None
        return list(self.positions)

    def order_calc_profit(self, otype, symbol, volume, p_open, p_close):
        d = (p_close - p_open) * (1 if otype == self.ORDER_TYPE_BUY else -1)
        return d * volume * self.info.trade_contract_size * self.account_per_usd
    def history_deals_get(self, position=None): return [d for d in self.deals if d.position_id == position]

    def order_check(self, req):
        self.checked.append(dict(req))
        r = self.check_script.pop(0) if self.check_script else 0
        if r == "NONE":
            return None
        return NS(retcode=r, comment="check")

    def order_send(self, req):
        self.sent.append(dict(req))
        b = self.send_script.pop(0) if self.send_script else self.TRADE_RETCODE_DONE
        if callable(b):
            return b(req)
        if b == "NONE":
            return None
        if b == "EXECUTED_BUT_NO_ANSWER":  # le serveur a exécuté mais la réponse est perdue
            self._execute(req)
            return None
        if b == self.TRADE_RETCODE_DONE and self.partial_fraction is not None and "position" not in req:
            ticket = self._execute({**req, "volume": round(req["volume"] * self.partial_fraction, 2)})
            return NS(retcode=self.TRADE_RETCODE_DONE_PARTIAL, comment="partial", price=req["price"], order=ticket, deal=ticket + 1)
        if b == self.TRADE_RETCODE_DONE:
            ticket = self._execute(req)
            return NS(retcode=b, comment="done", price=req["price"], order=ticket, deal=ticket + 1)
        return NS(retcode=b, comment="refus", price=0.0, order=0, deal=0)

    def _execute(self, req):
        if "position" in req:
            pos = next(p for p in self.positions if p.ticket == req["position"])
            self.positions = [p for p in self.positions if p.ticket != req["position"]]
            long = pos.type == self.POSITION_TYPE_BUY
            pnl = ((req["price"] - pos.price_open) if long else (pos.price_open - req["price"])) * pos.volume * self.info.trade_contract_size
            self.deals.append(NS(position_id=pos.ticket, profit=pnl, commission=-1.0, swap=0.0, fee=0.0, price=req["price"]))
            return pos.ticket
        self._ticket += 2
        self.positions.append(NS(ticket=self._ticket, magic=req["magic"], symbol=req["symbol"], volume=req["volume"],
                                 type=self.POSITION_TYPE_BUY if req["type"] == self.ORDER_TYPE_BUY else self.POSITION_TYPE_SELL,
                                 price_open=req["price"], sl=req["sl"], tp=req["tp"], comment=req.get("comment", "")))
        return self._ticket

    def server_side_exit(self, price):
        """SL/TP déclenché par le serveur."""
        for p in list(self.positions):
            self._execute({"position": p.ticket, "price": price})
