"""Moteur de backtest PESSIMISTE, partagé par backtest, paper et démo (aucun code dupliqué).

Règles : signal à la clôture de la barre i -> ordre exécuté à l'OUVERTURE de i+1. Les barres sont des
prix BID ; achat à l'ask (= bid + spread). Stop et cible dans la même barre : le stop gagne (sauf
résolution sur données fines). Gap au-delà du stop : exécution à l'ouverture (perte > 1R possible).
Équité en mark-to-market ; gardien prop firm sur l'équité.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import heapq
import math
import numpy as np
import pandas as pd
from ..instruments import value_per_unit
from .guardian import Guardian, PropProfile
from .market import Market


@dataclass
class SimConfig:
    risk_pct: float = 0.5            # % du capital risqué par trade
    compound: bool = False           # False : risque fixe sur le capital initial (mesure de R propre)
    leverage: float = 30.0
    min_rr_net: float = 2.5          # setup rejeté avant l'entrée si RR net < 2,5
    group_cap_mult: float = 1.0      # risque max ouvert par groupe corrélé = mult × risk_pct
    max_open_risk_mult: float = 3.0
    cost_mult: float = 1.0
    grades: tuple = (2, 1)           # A+ et A seulement
    stop_on_breach: bool = True
    use_guardian: bool = True
    initial_balance: float = 100000.0


@dataclass
class Pos:
    key: tuple
    sym: str
    algo: str
    side: int
    lots0: float
    lots: float
    entry: float
    stop: float
    target: float
    r_dist: float
    value: float
    risk_usd: float
    entry_t: int
    grade: int
    feat: object
    ex: object
    bars: int = 0
    pnl: float = 0.0
    comm: float = 0.0
    swap: float = 0.0
    best: float = 0.0       # meilleur excursion favorable (prix)
    worst: float = 0.0
    partial_done: bool = False
    be_done: bool = False
    trail_on: bool = False
    exit_next: str = ""
    last_close: float = 0.0
    last_adv: float = 0.0
    sig_t: int = 0
    exits: list = field(default_factory=list)
    spr_last: float = 0.0
    worst_r: float = 0.0
    best_r: float = 0.0
    last_j: int = 0


class Sim:
    def __init__(self, markets: dict[str, Market], cfg: SimConfig | None = None, profile: PropProfile | None = None):
        self.mk = markets
        self.cfg = cfg or SimConfig()
        self.prof = profile or PropProfile(initial_balance=self.cfg.initial_balance)
        self.cfg.initial_balance = self.prof.initial_balance
        self.g = Guardian(self.prof)
        self.balance = self.prof.initial_balance
        self.pos: list[Pos] = []
        self.pending: list[dict] = []
        self.trades: list[dict] = []
        self.rej: dict[str, int] = {}
        self.eq_t: list[int] = []
        self.eq_v: list[float] = []
        self.last_equity = self.balance
        self.day_trades: dict = {}
        self.passed_t = None
        self.events: list[dict] = []   # journal des décisions (paper/démo)
        self.dead = False

    # ------------------------------------------------------------------ utilitaires
    def _rej(self, why, **kw):
        self.rej[why] = self.rej.get(why, 0) + 1
        self.events.append({"type": "reject", "why": why, **kw})

    def equity(self):
        return self.balance + sum(self._upnl(p, p.last_close) for p in self.pos)

    def _upnl(self, p: Pos, px_bid: float):
        """P&L latent à la valeur de liquidation : long au bid, short à l'ask."""
        if p.side > 0:
            return (px_bid - p.entry) * p.lots * p.value
        return (p.entry - (px_bid + p.spr_last)) * p.lots * p.value

    def open_risk(self):
        return sum(max(0.0, p.side * (p.last_close - p.stop)) * p.lots * p.value for p in self.pos)

    def _group_risk(self, group):
        from ..instruments import SPECS
        return sum(p.risk_usd * p.lots / p.lots0 for p in self.pos if self.mk[p.sym].spec.group == group)

    # ------------------------------------------------------------------ boucle principale
    def run(self, signals: list, t0: int | None = None, t1: int | None = None):
        """signals : liste de Signals (algo × instrument). Barres traitées à la demande."""
        self.sig = {}
        sigbars: dict[str, set] = {}
        for s in signals:
            self.sig.setdefault(s.sym, []).append(s)
            ix = s.idx()
            sigbars.setdefault(s.sym, set()).update(ix.tolist())
        self.sigbars = {k: np.array(sorted(v), dtype="int64") for k, v in sigbars.items()}
        cur = {}
        for sym, mk in self.mk.items():
            if sym not in self.sigbars or len(self.sigbars[sym]) == 0:
                continue
            first = 0
            if t0 is not None:
                first = int(np.searchsorted(mk.t, t0))
            nj = self._nxt(sym, max(first, 0))
            if nj is not None:
                cur[sym] = nj
        while cur:
            sym = min(cur, key=lambda s: (self.mk[s].t[cur[s]] if cur[s] is not None else 1 << 62))
            j = cur[sym]
            if j is None or j >= self.mk[sym].n or (t1 is not None and self.mk[sym].t[j] >= t1):
                cur.pop(sym); continue
            self.process_bar(sym, j)
            if self.dead:
                break
            active = any(p.sym == sym for p in self.pos) or any(o["sym"] == sym for o in self.pending)
            nj = j + 1 if active else self._nxt(sym, j + 1)
            if nj is None or nj >= self.mk[sym].n:
                cur.pop(sym)
            else:
                cur[sym] = nj
        self._close_all("fin_donnees")
        return self.result()

    def _nxt(self, sym, frm):
        a = self.sigbars.get(sym)
        if a is None:
            return None
        k = int(np.searchsorted(a, frm))
        return int(a[k]) if k < len(a) else None

    # ------------------------------------------------------------------ une barre
    def process_bar(self, sym: str, j: int):
        mk = self.mk[sym]
        cfg = self.cfg
        t, o, h, l, c = int(mk.t[j]), mk.o[j], mk.h[j], mk.l[j], mk.c[j]
        d = int(mk.pday[j])
        if d != self.g.day:
            self.g.new_day(d, self.balance, self.last_equity)
            self.day_trades = {}
        mine = [p for p in self.pos if p.sym == sym]
        # 1) exécution des ordres en attente à l'ouverture
        for od in [x for x in self.pending if x["sym"] == sym]:
            self.pending.remove(od)
            self._fill(od, mk, j)
        # 2) sorties
        for p in [p for p in self.pos if p.sym == sym]:
            self._manage(p, mk, j)
        # 3) équité, gardien
        for p in self.pos:
            if p.sym == sym:
                p.last_j = j; p.last_close = c; p.spr_last = mk.spr[j] * cfg.cost_mult * mk.news_mult[j]
                p.last_adv = l if p.side > 0 else h + p.spr_last
        eq = self.equity()
        worst = self.balance + sum(((p.last_adv - p.entry) if p.side > 0 else (p.entry - p.last_adv)) * p.lots * p.value
                                   for p in self.pos)
        if cfg.use_guardian:
            br = self.g.check_official(worst, t)
            if br:
                self.dead = cfg.stop_on_breach
                self.events.append({"type": "breach", **br})
            act = self.g.check_close(eq)
            if act:
                self.events.append({"type": "guardian", "action": act, "t": t, "equity": eq})
                self._close_all(act, only_cost=True)
                eq = self.equity()
        self.last_equity = eq
        if not self.eq_t or self.eq_t[-1] != int(mk.tc[j]):
            self.eq_t.append(int(mk.tc[j])); self.eq_v.append(eq)
        else:
            self.eq_v[-1] = eq
        if (self.passed_t is None and eq - self.prof.initial_balance >= self.prof.target
                and len(self.g.trading_days) >= self.prof.min_trading_days):
            self.passed_t = t
        # 4) nouveaux signaux à la clôture de la barre j
        if not self.dead:
            for s in self.sig.get(sym, []):
                if s.side[j] != 0:
                    self._signal(s, mk, j)

    def _signal(self, s, mk: Market, j: int):
        cfg = self.cfg
        key = (s.algo, s.sym)
        if int(s.grade[j]) not in cfg.grades:
            return self._rej("grade", key=key)
        if any(p.key == key for p in self.pos) or any(o["key"] == key for o in self.pending):
            return self._rej("deja_en_position", key=key)
        if mk.gap_next[j]:
            return self._rej("pre_gap", key=key)
        if mk.news_block_next[j] and not s.allow_news:
            return self._rej("annonce", key=key)
        dk = (key, self.g.day)
        if self.day_trades.get(dk, 0) >= s.max_per_day:
            return self._rej("max_par_jour", key=key)
        self.pending.append({"key": key, "sym": s.sym, "algo": s.algo, "side": int(s.side[j]), "stop": float(s.stop[j]),
                             "target": float(s.target[j]), "grade": int(s.grade[j]), "ex": s.exit,
                             "feat": None if s.feat is None else s.feat[j].copy(), "sig_t": int(mk.t[j]),
                             "ref": float(mk.c[j]), "allow_news": s.allow_news})
        self.events.append({"type": "signal", "key": key, "side": int(s.side[j]), "t": int(mk.tc[j]),
                            "grade": int(s.grade[j]), "stop": float(s.stop[j]), "target": float(s.target[j]),
                            "ref": float(mk.c[j])})

    # ------------------------------------------------------------------ entrée
    def _fill(self, od, mk: Market, j: int):
        cfg, spec = self.cfg, mk.spec
        side = od["side"]; ex = od["ex"]
        spr = mk.spr[j] * cfg.cost_mult * mk.news_mult[j]
        slip = spec.slippage * cfg.cost_mult * mk.news_mult[j] * (1.0 if mk.news_mult[j] == 1.0 else 1.5)
        o = mk.o[j]
        entry = o + spr + slip if side > 0 else o - slip   # long : ask ; short : bid
        stop = od["stop"]
        if not np.isfinite(stop) or side * (entry - stop) <= 0:
            return self._rej("stop_invalide_au_fill", key=od["key"])
        r_dist = side * (entry - stop)
        tgt = od["target"]
        if not np.isfinite(tgt):
            tgt = entry + side * ex.rr * abs(od["ref"] - stop)
        # le « prix » du côté sortie d'un short est l'ask : cible/stop exprimés côté exécution
        value = value_per_unit(spec, entry)
        comm_unit = spec.commission_lot * cfg.cost_mult / value   # commission en unités de prix
        reward = side * (tgt - entry)
        if reward <= 0:
            return self._rej("cible_invalide", key=od["key"])
        exit_slip = slip
        rr_net = (reward - comm_unit - (spr if side < 0 else 0.0)) / (r_dist + exit_slip + comm_unit + (spr if side < 0 else 0.0))
        if rr_net < cfg.min_rr_net:
            return self._rej("rr_net", key=od["key"], rr=round(rr_net, 2))
        base = self.balance if cfg.compound else self.prof.initial_balance
        risk_usd = base * cfg.risk_pct / 100
        per_lot = (r_dist + exit_slip + (spr if side < 0 else 0.0)) * value + spec.commission_lot * cfg.cost_mult
        lots = math.floor(risk_usd / per_lot / spec.lot_step + 1e-9) * spec.lot_step
        cap = cfg.leverage * self.balance / max(value * entry, 1e-9)
        lots = min(lots, spec.max_lot, math.floor(cap / spec.lot_step) * spec.lot_step)
        lots = round(lots, 8)
        if lots < spec.min_lot:
            return self._rej("lot_min", key=od["key"])
        real_risk = lots * per_lot
        grp = spec.group
        if self._group_risk(grp) + real_risk > cfg.group_cap_mult * base * cfg.risk_pct / 100 * 1.0001 + 1e-9 and \
                any(self.mk[p.sym].spec.group == grp for p in self.pos):
            return self._rej("plafond_groupe", key=od["key"])
        tot_open = sum(p.risk_usd * p.lots / p.lots0 for p in self.pos)
        if tot_open + real_risk > cfg.max_open_risk_mult * base * cfg.risk_pct / 100 * 1.0001:
            return self._rej("plafond_risque_global", key=od["key"])
        if cfg.use_guardian:
            ok, why = self.g.can_open(self.last_equity, self.open_risk(), real_risk)
            if not ok:
                return self._rej(why, key=od["key"])
        comm = spec.commission_lot * lots * cfg.cost_mult
        self.balance -= comm
        p = Pos(od["key"], mk.sym, od["algo"], side, lots, lots, entry, stop, tgt, r_dist, value, real_risk,
                int(mk.t[j]), od["grade"], od["feat"], ex, comm=comm, last_close=mk.c[j], sig_t=od["sig_t"],
                last_j=j, spr_last=spr)
        self.pos.append(p)
        self.g.trading_days.add(int(mk.pday[j]))
        dk = (od["key"], self.g.day)
        self.day_trades[dk] = self.day_trades.get(dk, 0) + 1
        self.events.append({"type": "open", "key": od["key"], "side": side, "t": int(mk.t[j]), "entry": entry,
                            "stop": stop, "target": tgt, "lots": lots, "risk_usd": real_risk, "rr_net": round(rr_net, 2),
                            "grade": od["grade"]})

    # ------------------------------------------------------------------ gestion / sortie
    def _manage(self, p: Pos, mk: Market, j: int):
        cfg, spec, ex = self.cfg, mk.spec, p.ex
        o, h, l, c = mk.o[j], mk.h[j], mk.l[j], mk.c[j]
        spr = mk.spr[j] * cfg.cost_mult * mk.news_mult[j]
        slip = spec.slippage * cfg.cost_mult * mk.news_mult[j]
        sd = p.side
        entered_now = p.bars == 0 and mk.t[j] == p.entry_t
        # swaps (nuits traversées en entrant dans la barre)
        if not entered_now and mk.roll[j] > 0:
            sw = (spec.swap_long if sd > 0 else spec.swap_short) * mk.roll[j] * p.lots * cfg.cost_mult
            p.swap += sw; self.balance += sw
        # sortie programmée à l'ouverture (stop temporel / garde)
        if p.exit_next:
            px = o - slip if sd > 0 else o + spr + slip
            return self._exit(p, px, p.exit_next, mk, j, at_open=True)
        ask_h = h + spr; ask_l = l + spr
        # prix « côté exécution » : long -> bid ; short -> ask
        hi, lo = (h, l) if sd > 0 else (ask_h, ask_l)
        op = o if sd > 0 else o + spr
        S, T = p.stop, p.target
        # gap sur le stop : exécution à l'ouverture
        if sd * (op - S) <= 0:
            return self._exit(p, op, "stop_gap", mk, j, at_open=True)
        stop_hit = (lo <= S) if sd > 0 else (hi >= S)
        tgt_hit = (hi >= T) if sd > 0 else (lo <= T)
        if sd * (op - T) >= 0:
            return self._exit(p, op, "cible_gap", mk, j, at_open=True)
        part_px = p.entry + sd * ex.partial_at * p.r_dist
        part_hit = ex.mode == "partial" and not p.partial_done and ((hi >= part_px) if sd > 0 else (lo <= part_px))
        if stop_hit and (tgt_hit or part_hit):
            first = self._fine_first(mk, j, sd, S, T if tgt_hit else part_px, spr)
            if first != "target":
                return self._exit(p, S - sd * slip, "stop", mk, j)
        elif stop_hit:
            return self._exit(p, S - sd * slip, "stop", mk, j)
        if part_hit:
            self._partial(p, part_px, mk, j)
            if stop_hit and not tgt_hit:
                return self._exit(p, S - sd * slip, "stop", mk, j)
        if tgt_hit:
            return self._exit(p, T, "cible", mk, j)
        # mise à jour à la clôture (effective à la barre suivante)
        p.bars += 1
        fav = (h - p.entry) if sd > 0 else (p.entry - ask_l)
        adv = (p.entry - l) if sd > 0 else (ask_h - p.entry)
        p.worst_r = max(p.worst_r, adv / p.r_dist)
        p.best_r = max(p.best_r, fav / p.r_dist)
        mfe_r = p.best_r
        if ex.mode in ("be", "partial") and not p.be_done and (mfe_r >= ex.be_at if ex.mode == "be" else p.partial_done):
            p.stop = p.entry; p.be_done = True
        if ex.mode in ("trail_atr", "trail_struct") and mfe_r >= ex.trail_after:
            p.trail_on = True
        if p.trail_on:
            if ex.mode == "trail_atr":
                ns_ = (c - ex.atr_k * mk.atr[j]) if sd > 0 else (c + ex.atr_k * mk.atr[j] + spr)
            else:
                ns_ = mk.swing_lo[j] if sd > 0 else mk.swing_hi[j] + spr
            if sd * (ns_ - p.stop) > 0 and sd * (c - ns_) > 0:
                p.stop = ns_
        if ex.time_stop and p.bars >= ex.time_stop:
            p.exit_next = "stop_temporel"
        elif ex.weekend_flat and mk.gap_next[j]:
            px = c - slip if sd > 0 else c + spr + slip
            return self._exit(p, px, "weekend", mk, j)

    def _fine_first(self, mk: Market, j: int, sd, S, T, spr):
        """Si des données plus fines existent, détermine quel niveau est touché en premier."""
        f = mk.fine
        if not f:
            return "stop"
        a = np.searchsorted(f["t"], mk.t[j]); b = np.searchsorted(f["t"], mk.tc[j])
        for k in range(a, b):
            hh, ll = f["h"][k], f["l"][k]
            if sd > 0:
                s_hit, t_hit = ll <= S, hh >= T
            else:
                s_hit, t_hit = hh + spr >= S, ll + spr <= T
            if s_hit and t_hit:
                return "stop"
            if s_hit:
                return "stop"
            if t_hit:
                return "target"
        return "stop"

    def _partial(self, p: Pos, px, mk: Market, j: int):
        step = mk.spec.lot_step
        q = math.floor(p.lots * p.ex.partial_frac / step + 1e-9) * step
        if q < mk.spec.min_lot or p.lots - q < mk.spec.min_lot:
            p.partial_done = True  # impossible de scinder : on bascule seulement au BE
            return
        g = p.side * (px - p.entry) * q * p.value
        p.pnl += g; self.balance += g; p.lots = round(p.lots - q, 8); p.partial_done = True
        p.exits.append(("partielle", px, q))
        self.events.append({"type": "partial", "key": p.key, "t": int(mk.t[j]), "px": px, "lots": q})

    def _exit(self, p: Pos, px, reason, mk: Market, j: int, at_open=False):
        g = p.side * (px - p.entry) * p.lots * p.value
        p.pnl += g; self.balance += g
        p.exits.append((reason, px, p.lots))
        net = p.pnl - p.comm + p.swap
        r = net / p.risk_usd if p.risk_usd else 0.0
        self.trades.append({"sym": p.sym, "algo": p.algo, "side": p.side, "entry_t": p.entry_t,
                            "exit_t": int(mk.t[j]) if at_open else int(mk.tc[j]),
                            "entry": p.entry, "exit": px, "lots": p.lots0, "risk_usd": p.risk_usd,
                            "pnl": net, "r": r, "gross_r": (p.pnl) / p.risk_usd if p.risk_usd else 0.0,
                            "mae_r": p.worst_r, "mfe_r": p.best_r,
                            "bars": p.bars + 1, "reason": reason, "grade": p.grade, "sig_t": p.sig_t,
                            "feat": p.feat, "r_dist": p.r_dist})
        self.events.append({"type": "close", "key": p.key, "t": int(mk.t[j]) if at_open else int(mk.tc[j]), "px": px, "reason": reason, "r": r,
                            "pnl": net})
        self.pos.remove(p)

    def _close_all(self, reason, only_cost=False):
        """Fermeture forcée (gardien, fin de données) à la dernière clôture connue de chaque position."""
        for p in list(self.pos):
            mk = self.mk[p.sym]
            j = min(p.last_j, mk.n - 1)
            spr = mk.spr[j] * self.cfg.cost_mult
            slip = mk.spec.slippage * self.cfg.cost_mult
            c = p.last_close or mk.c[j]
            self._exit(p, c - slip if p.side > 0 else c + spr + slip, reason, mk, j)

    def result(self):
        tr = pd.DataFrame(self.trades)
        return SimResult(tr, np.array(self.eq_t, dtype="int64"), np.array(self.eq_v), self.g.breach, dict(self.rej),
                         self.passed_t, sorted(self.g.trading_days), self.events)


@dataclass
class SimResult:
    trades: pd.DataFrame
    eq_t: np.ndarray
    eq_v: np.ndarray
    breach: dict | None
    rejected: dict
    passed_t: int | None
    trading_days: list
    events: list
