"""État persistant du bot en direct (SQLite) : intentions d'ordres, événements, clé/valeur.

Principe write-ahead : une intention est ÉCRITE (statut PENDING) AVANT tout appel à order_send. Au redémarrage, une
intention PENDING/SENT/UNKNOWN est réconciliée avec le terminal : jamais rejouée à l'aveugle.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from ..exceptions import MemoryStoreError

# PENDING -> SENT -> CONFIRMED ; REFUSED (order_check/serveur) ; FAILED (erreur avant envoi) ; UNKNOWN (réponse ambiguë)
OPEN_STATUSES = ("PENDING", "SENT", "UNKNOWN")
SCHEMA = """
CREATE TABLE IF NOT EXISTS intents (
  id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL, kind TEXT NOT NULL, side TEXT,
  status TEXT NOT NULL, plan TEXT, detail TEXT, ticket INTEGER, strategy TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, level TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS executions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, intent_id TEXT, kind TEXT NOT NULL, symbol TEXT, side TEXT, volume REAL,
  expected_price REAL, fill_price REAL, slippage REAL, latency_ms REAL, retcode INTEGER, ticket INTEGER);
CREATE INDEX IF NOT EXISTS idx_exec_ts ON executions(ts);
CREATE INDEX IF NOT EXISTS idx_exec_intent ON executions(intent_id);
CREATE TRIGGER IF NOT EXISTS executions_no_update BEFORE UPDATE ON executions BEGIN SELECT RAISE(ABORT, 'journal d''exécution append-only'); END;
CREATE TRIGGER IF NOT EXISTS executions_no_delete BEFORE DELETE ON executions BEGIN SELECT RAISE(ABORT, 'journal d''exécution append-only'); END;
"""


class StateStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        try:
            self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.executescript(SCHEMA)
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Ouverture de l'état impossible ({path}) : {exc}") from exc

    def _x(self, sql: str, params: tuple = ()):
        with self._lock:
            try:
                return self.db.execute(sql, params)
            except sqlite3.Error as exc:
                raise MemoryStoreError(f"Écriture d'état échouée : {exc}") from exc

    # --- intentions ----------------------------------------------------------
    def new_intent(self, kind: str, side: str, plan: dict, strategy: str = "") -> str:
        iid = uuid.uuid4().hex[:16]
        now = time.time()
        self._x("INSERT INTO intents (id,created,updated,kind,side,status,plan,strategy) VALUES (?,?,?,?,?,?,?,?)",
                (iid, now, now, kind, side, "PENDING", json.dumps(plan, default=str), strategy))
        return iid

    def mark(self, iid: str, status: str, detail: str = "", ticket: Optional[int] = None) -> None:
        self._x("UPDATE intents SET status=?, detail=?, updated=?, ticket=COALESCE(?, ticket) WHERE id=?",
                (status, detail[:500], time.time(), ticket, iid))

    def intent(self, iid: str) -> Optional[dict]:
        r = self._x("SELECT * FROM intents WHERE id=?", (iid,)).fetchone()
        return dict(r) if r else None

    def open_intents(self) -> list[dict]:
        q = ",".join("?" * len(OPEN_STATUSES))
        return [dict(r) for r in self._x(f"SELECT * FROM intents WHERE status IN ({q}) ORDER BY created", OPEN_STATUSES).fetchall()]

    def unknown_intents(self) -> list[dict]:
        return [dict(r) for r in self._x("SELECT * FROM intents WHERE status='UNKNOWN' ORDER BY created").fetchall()]

    def recent_intents(self, n: int = 20) -> list[dict]:
        return [dict(r) for r in self._x("SELECT * FROM intents ORDER BY created DESC LIMIT ?", (n,)).fetchall()]

    def known_tickets(self) -> set[int]:
        return {r[0] for r in self._x("SELECT ticket FROM intents WHERE ticket IS NOT NULL").fetchall()}

    # --- clé/valeur & événements ----------------------------------------------
    def set(self, key: str, value: Any) -> None:
        self._x("INSERT INTO kv (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, default=str)))

    def get(self, key: str, default: Any = None) -> Any:
        r = self._x("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def delete(self, key: str) -> None:
        self._x("DELETE FROM kv WHERE key=?", (key,))

    def record_execution(self, intent_id: str, kind: str, symbol: str, side: str, volume: float, expected_price: float, fill_price: Optional[float],
                         t_send: float, t_ack: float, retcode: Optional[int] = None, ticket: Optional[int] = None) -> None:
        """Journal d'audit APPEND-ONLY (UPDATE/DELETE interdits par déclencheur) : latence d'envoi->réponse en ms (horloge monotone fournie par l'appelant) et glissement
        signé (positif = défavorable : achat rempli plus haut / vente remplie plus bas que le prix attendu)."""
        slip = None if fill_price is None else (fill_price - expected_price) * (1.0 if side in ("long", "buy") else -1.0)
        self._x("INSERT INTO executions (ts, intent_id, kind, symbol, side, volume, expected_price, fill_price, slippage, latency_ms, retcode, ticket) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), intent_id, kind, symbol, side, volume, expected_price, fill_price, slip, (t_ack - t_send) * 1000.0, retcode, ticket))

    def executions(self, n: int = 50) -> list[dict]:
        with self._lock:
            cur = self.db.execute("SELECT * FROM executions ORDER BY id DESC LIMIT ?", (n,)); cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def log(self, level: str, kind: str, detail: str = "") -> None:
        self._x("INSERT INTO events (ts,level,kind,detail) VALUES (?,?,?,?)", (time.time(), level, kind, detail[:500]))

    def recent_events(self, n: int = 30) -> list[dict]:
        return [dict(r) for r in self._x("SELECT * FROM events ORDER BY id DESC LIMIT ?", (n,)).fetchall()]

    def close(self) -> None:
        self.db.close()
