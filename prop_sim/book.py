"""Livre de positions virtuelles persistant (SQLite).

- Déduplication des signaux par `signal_id`, des barres par (paire, horodatage).
- Reprise : rouvrir la base et rejouer le flux (même depuis le début) est
  idempotent.
- Chaque signal, rejet, remplissage et clôture est écrit dans `events`.
- Les barres fournies sont des prix MILIEU (mid) ; bid/ask = mid ± spread/2.
  Le spread est fourni par l'appelant (mesuré, ou substitut de recherche à
  identifier comme tel). Aucune connexion courtier.
- Collision stop/objectif dans une même barre : le stop est supposé touché
  en premier (hypothèse pessimiste, tracée dans l'événement). Gap à
  l'ouverture au-delà du stop : exécution au prix d'ouverture, pas au stop.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field

import pandas as pd

from .ftmo import prague_day
from .instruments_ext import PIP_SIZE, loss_at, pnl_usd
from .risk_engine import OpenRisk, RiskEngine, RiskLimits

LOT_STEP_UNITS = 1_000  # 0,01 lot

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS strategies(id TEXT PRIMARY KEY, params_hash TEXT, status TEXT, params TEXT);
CREATE TABLE IF NOT EXISTS signals(signal_id TEXT PRIMARY KEY, ts TEXT, pair TEXT, strategy_id TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS positions(signal_id TEXT PRIMARY KEY, pair TEXT, direction TEXT, units REAL,
  stop REAL, target REAL, status TEXT, signal_ts TEXT, risk_pct REAL, entry REAL, entry_ts TEXT,
  exit REAL, exit_ts TEXT, reason TEXT, pnl REAL, costs REAL, strategy_id TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, signal_id TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS equity(ts TEXT PRIMARY KEY, balance REAL, equity REAL);
"""


@dataclass
class Signal:
    signal_id: str
    ts: pd.Timestamp          # horodatage de la barre qui a produit le signal (UTC)
    pair: str
    direction: str            # long | short
    stop: float
    target: float
    strategy_id: str
    meta: dict = field(default_factory=dict)


@dataclass
class ExecutionModel:
    slippage_pips: float = 0.2
    commission_per_lot: float = 7.0   # aller-retour, USD
    swap_usd_per_lot_day: float = 0.0  # non modélisé tant que non fourni par le courtier


class VirtualBook:
    def __init__(self, path: str, initial_balance: float = 100_000.0,
                 limits: RiskLimits | None = None, execution: ExecutionModel | None = None):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.limits = limits or RiskLimits()
        self.risk = RiskEngine(self.limits)
        self.exe = execution or ExecutionModel()
        fp = self.limits.fingerprint()
        stored = self._meta("limits_fp")
        if stored is not None and stored != fp:
            raise RuntimeError("Les limites de risque ont changé depuis la création de ce livre "
                               f"({stored} -> {fp}) : ouvrir un nouveau livre.")
        self._set_meta("limits_fp", fp)
        if self._meta("initial_balance") is None:
            self._set_meta("initial_balance", initial_balance)
            self._set_meta("balance", initial_balance)
        self.initial_balance = float(self._meta("initial_balance"))

    # ---- meta / événements -------------------------------------------------
    def _meta(self, k):
        r = self.db.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
        return None if r is None else r[0]

    def _set_meta(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, str(v)))

    def _event(self, ts, kind, signal_id, **payload):
        self.db.execute("INSERT INTO events(ts,kind,signal_id,payload) VALUES(?,?,?,?)",
                        (str(ts), kind, signal_id, json.dumps(payload, default=str)))

    @property
    def balance(self) -> float:
        return float(self._meta("balance"))

    # ---- registre des stratégies ------------------------------------------
    def register_strategy(self, strategy_id: str, params: dict, status: str = "research"):
        """Toute modification des paramètres change l'empreinte et ramène le
        statut à 'research' : l'approbation précédente est invalidée."""
        h = hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:16]
        r = self.db.execute("SELECT params_hash,status FROM strategies WHERE id=?", (strategy_id,)).fetchone()
        if r is None:
            self.db.execute("INSERT INTO strategies VALUES(?,?,?,?)",
                            (strategy_id, h, status, json.dumps(params, sort_keys=True, default=str)))
        elif r[0] != h:
            self.db.execute("UPDATE strategies SET params_hash=?,status='research',params=? WHERE id=?",
                            (h, json.dumps(params, sort_keys=True, default=str), strategy_id))
            self._event("-", "strategy_changed", strategy_id, old=r[0], new=h, was=r[1])
        self.db.commit()
        return h

    def set_strategy_status(self, strategy_id: str, status: str):
        """À appeler par un humain/processus de promotion, jamais par un signal."""
        self.db.execute("UPDATE strategies SET status=? WHERE id=?", (status, strategy_id))
        self.db.commit()

    # ---- état du compte -----------------------------------------------------
    def _open_rows(self, statuses=("open",)):
        q = ",".join("?" * len(statuses))
        return self.db.execute(
            f"SELECT signal_id,pair,direction,units,stop,target,risk_pct,entry,status,signal_ts "
            f"FROM positions WHERE status IN ({q})", statuses).fetchall()

    def _last_price(self, pair):
        v = self._meta(f"px:{pair}")
        return None if v is None else json.loads(v)  # [mid, spread_pips]

    def floating(self) -> float:
        tot = 0.0
        for _, pair, d, units, _, _, _, entry, _, _ in self._open_rows():
            px = self._last_price(pair)
            if px is None:
                continue
            mid, spr = px
            half = spr * PIP_SIZE[pair] / 2
            exit_px = mid - half if d == "long" else mid + half
            tot += pnl_usd(pair, entry, exit_px, d, units)
        return tot

    def equity(self) -> float:
        return self.balance + self.floating()

    def _roll_day(self, ts):
        day = str(prague_day(ts))
        if self._meta("day") != day:
            self._set_meta("day", day)
            self._set_meta("day_start_equity", self.equity())
            self._set_meta("signals_today", 0)

    # ---- signaux -----------------------------------------------------------
    def submit_signal(self, sig: Signal, risk_pct: float | None = None) -> str:
        ts = pd.Timestamp(sig.ts)
        if self.db.execute("SELECT 1 FROM signals WHERE signal_id=?", (sig.signal_id,)).fetchone():
            return "duplicate"
        last = self._meta(f"bar:{sig.pair}")
        outcome, reasons = "queued", ()
        row = self.db.execute("SELECT status FROM strategies WHERE id=?", (sig.strategy_id,)).fetchone()
        if last is not None and ts < pd.Timestamp(last):
            outcome, reasons = "rejected", ("stale_signal",)
        elif row is None or row[0] != "forward_test":
            outcome, reasons = "rejected", (f"strategy_not_in_forward_test:{row[0] if row else 'unregistered'}",)
        elif not (sig.stop < sig.target if sig.direction == "long" else sig.stop > sig.target):
            outcome, reasons = "rejected", ("invalid_stop_target",)
        else:
            self._roll_day(ts)
            risk_pct = risk_pct if risk_pct is not None else self.limits.risk_per_trade_pct
            opens = [OpenRisk(p, d, rp) for _, p, d, _, _, _, rp, _, st, _ in self._open_rows(("open", "pending"))]
            dec = self.risk.evaluate(
                pair=sig.pair, direction=sig.direction, risk_pct=risk_pct, equity=self.equity(),
                day_start_equity=float(self._meta("day_start_equity")), initial_balance=self.initial_balance,
                open_risks=opens, signals_today=int(self._meta("signals_today")))
            if not dec.approved:
                outcome, reasons = "rejected", dec.reasons
            else:
                self._set_meta("signals_today", int(self._meta("signals_today")) + 1)
                self.db.execute(
                    "INSERT INTO positions(signal_id,pair,direction,units,stop,target,status,signal_ts,risk_pct,strategy_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (sig.signal_id, sig.pair, sig.direction, 0, sig.stop, sig.target, "pending",
                     str(ts), risk_pct, sig.strategy_id))
        self.db.execute("INSERT INTO signals VALUES(?,?,?,?,?)",
                        (sig.signal_id, str(ts), sig.pair, sig.strategy_id, outcome))
        self._event(ts, "signal", sig.signal_id, outcome=outcome, reasons=reasons, pair=sig.pair,
                    direction=sig.direction, stop=sig.stop, target=sig.target, meta=sig.meta)
        self.db.commit()
        return outcome if outcome == "queued" else f"rejected:{','.join(reasons)}"

    # ---- barres ------------------------------------------------------------
    def on_bar(self, pair, ts, o, h, l, c, spread_pips) -> bool:
        """Retourne False si la barre a déjà été traitée (rejeu/reprise)."""
        ts = pd.Timestamp(ts)
        last = self._meta(f"bar:{pair}")
        if last is not None and ts <= pd.Timestamp(last):
            return False
        self._roll_day(ts)
        half = spread_pips * PIP_SIZE[pair] / 2
        slip = self.exe.slippage_pips * PIP_SIZE[pair]

        for sid, p, d, _, stop, target, risk_pct, _, st, sts in self._open_rows(("pending",)):
            if p != pair or pd.Timestamp(sts) >= ts:
                continue
            self._fill(sid, pair, d, ts, o, half, slip, stop, target, risk_pct)

        for sid, p, d, units, stop, target, _, entry, st, _ in self._open_rows():
            if p != pair:
                continue
            self._check_exit(sid, pair, d, units, stop, target, entry, ts, o, h, l, half, slip)

        self._set_meta(f"bar:{pair}", ts)
        self._set_meta(f"px:{pair}", json.dumps([c, spread_pips]))
        self.db.execute("INSERT OR REPLACE INTO equity VALUES(?,?,?)", (str(ts), self.balance, self.equity()))
        self.db.commit()
        return True

    def _fill(self, sid, pair, d, ts, o, half, slip, stop, target, risk_pct):
        entry = o + half + slip if d == "long" else o - half - slip
        per_unit = loss_at(pair, entry, stop, d)  # perte USD par unité au stop
        comm_per_unit = self.exe.commission_per_lot / 100_000
        risk_amount = self.equity() * risk_pct / 100
        raw = risk_amount / (per_unit + comm_per_unit) if per_unit > 0 else 0
        units = int(raw // LOT_STEP_UNITS) * LOT_STEP_UNITS
        wrong_side = (entry <= stop or entry >= target) if d == "long" else (entry >= stop or entry <= target)
        reason = "entry_beyond_stop_or_target" if wrong_side else ("below_min_lot" if units <= 0 else None)
        if reason:
            self.db.execute("UPDATE positions SET status='rejected',reason=? WHERE signal_id=?", (reason, sid))
            self._event(ts, "reject_fill", sid, reason=reason, entry=entry)
            return
        self.db.execute("UPDATE positions SET status='open',units=?,entry=?,entry_ts=? WHERE signal_id=?",
                        (units, entry, str(ts), sid))
        self._event(ts, "fill", sid, entry=entry, units=units, spread_half=half, slip=slip,
                    risk_at_stop_usd=units * per_unit)

    def _check_exit(self, sid, pair, d, units, stop, target, entry, ts, o, h, l, half, slip):
        if d == "long":   # sorties au bid
            bo, bh, bl = o - half, h - half, l - half
            gap_stop, gap_tgt = bo <= stop, bo >= target
            hit_stop, hit_tgt = bl <= stop, bh >= target
        else:             # sorties à l'ask
            bo, bh, bl = o + half, h + half, l + half
            gap_stop, gap_tgt = bo >= stop, bo <= target
            hit_stop, hit_tgt = bh >= stop, bl <= target
        if not (hit_stop or hit_tgt):
            return
        note = ""
        if gap_stop:
            px, reason = bo, "stop_gap"
        elif gap_tgt:
            px, reason = bo, "target_gap"
        elif hit_stop:
            px, reason = (stop - slip if d == "long" else stop + slip), "stop"
            if hit_tgt:
                note = "stop_first_collision"
        else:
            px, reason = target, "target"  # limite : pas de slippage défavorable
        gross = pnl_usd(pair, entry, px, d, units)
        costs = self.exe.commission_per_lot * units / 100_000
        pnl = gross - costs
        self.db.execute("UPDATE positions SET status='closed',exit=?,exit_ts=?,reason=?,pnl=?,costs=? WHERE signal_id=?",
                        (px, str(ts), reason, pnl, costs, sid))
        self._set_meta("balance", self.balance + pnl)
        self._event(ts, "close", sid, reason=reason, note=note, exit=px, pnl=pnl, costs=costs)

    # ---- sorties pour analyse ---------------------------------------------
    def equity_curve(self) -> pd.DataFrame:
        df = pd.read_sql("SELECT ts,balance,equity FROM equity ORDER BY ts", self.db)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return df.set_index("ts")

    def trades(self) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM positions WHERE status='closed' ORDER BY entry_ts", self.db)

    def trading_days(self) -> set:
        days = set()
        for (ts,) in self.db.execute("SELECT ts FROM events WHERE kind IN ('fill','close')"):
            days.add(prague_day(pd.Timestamp(ts)))
        return days

    def rejection_summary(self) -> dict:
        out: dict = {}
        for (p,) in self.db.execute("SELECT payload FROM events WHERE kind='signal'"):
            j = json.loads(p)
            key = j["outcome"] if j["outcome"] == "queued" else "|".join(j["reasons"])
            out[key] = out.get(key, 0) + 1
        for (p,) in self.db.execute("SELECT payload FROM events WHERE kind='reject_fill'"):
            k = "fill:" + json.loads(p)["reason"]
            out[k] = out.get(k, 0) + 1
        return out

    def close(self):
        self.db.commit()
        self.db.close()
