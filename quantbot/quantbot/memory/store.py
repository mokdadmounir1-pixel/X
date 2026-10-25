"""Mémoire & observabilité : toutes les expériences, versions et trades (SQLite)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from ..config import Settings
from ..exceptions import MemoryStoreError
from ..execution.broker import Trade
from ..logging_utils import get_logger

log = get_logger("memory")

STATUSES = {"baseline", "tested", "rejected", "improved", "promoted"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version TEXT NOT NULL,
  parent TEXT,
  change TEXT,
  overrides TEXT,
  settings TEXT NOT NULL,
  status TEXT NOT NULL,
  oos_return REAL, max_dd REAL, profit_factor REAL, n_trades INTEGER,
  report TEXT, reason TEXT, notes TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version TEXT NOT NULL,
  side TEXT, entry_time TEXT, exit_time TEXT, entry REAL, exit REAL, size REAL,
  pnl REAL, reason TEXT, patterns TEXT, confidence REAL
);
CREATE TABLE IF NOT EXISTS learnings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version TEXT, note TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ExperimentStore:
    def __init__(self, path: str = ":memory:") -> None:
        try:
            self.db = sqlite3.connect(path)
            self.db.row_factory = sqlite3.Row
            self.db.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Ouverture de la base impossible ({path}) : {exc}") from exc

    def close(self) -> None:
        self.db.close()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        try:
            with self.db:
                return self.db.execute(sql, params)
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Requête échouée : {exc}") from exc

    # --- expériences -----------------------------------------------------
    def add_experiment(self, version: str, settings: Settings, status: str, parent: Optional[str] = None,
                       change: str = "", overrides: Optional[dict] = None, metrics: Optional[dict] = None,
                       report: Optional[dict] = None, reason: str = "", notes: str = "") -> int:
        if status not in STATUSES:
            raise MemoryStoreError(f"Statut inconnu : {status}")
        m = metrics or {}
        cur = self._exec(
            "INSERT INTO experiments (version,parent,change,overrides,settings,status,oos_return,max_dd,"
            "profit_factor,n_trades,report,reason,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (version, parent, change, json.dumps(overrides or {}), json.dumps(settings.to_dict()), status,
             m.get("total_return"), m.get("max_drawdown"), _finite(m.get("profit_factor")), m.get("n_trades"),
             json.dumps(report, default=str) if report else None, reason, notes, _now()))
        return int(cur.lastrowid)

    def update_status(self, exp_id: int, status: str, reason: str = "") -> None:
        if status not in STATUSES:
            raise MemoryStoreError(f"Statut inconnu : {status}")
        self._exec("UPDATE experiments SET status=?, reason=? WHERE id=?", (status, reason, exp_id))

    def promote(self, version: str, reason: str = "approuvée manuellement") -> None:
        """Promeut une version validée (statut 'improved') — approbation humaine en réel."""
        row = self.db.execute("SELECT id, status FROM experiments WHERE version=? ORDER BY id DESC LIMIT 1",
                              (version,)).fetchone()
        if row is None:
            raise MemoryStoreError(f"Version inconnue : {version}")
        if row["status"] not in ("improved", "promoted"):
            raise MemoryStoreError(f"{version} est '{row['status']}' : seules les versions validées sont promouvables")
        self.update_status(row["id"], "promoted", reason)

    def history(self) -> list[dict]:
        rows = self.db.execute("SELECT id,version,parent,change,status,oos_return,max_dd,profit_factor,"
                               "n_trades,reason,created_at FROM experiments ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def current(self) -> Optional[tuple[str, Settings]]:
        """Dernière version promue (ou baseline)."""
        row = self.db.execute("SELECT version,settings FROM experiments WHERE status IN ('promoted','baseline') "
                              "ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return row["version"], Settings.from_dict(json.loads(row["settings"]))

    def next_version(self) -> str:
        n = self.db.execute("SELECT COUNT(DISTINCT version) FROM experiments").fetchone()[0]
        return f"v{n}"

    def failed_changes(self) -> list[dict]:
        rows = self.db.execute("SELECT change, overrides, reason FROM experiments WHERE status='rejected'").fetchall()
        return [dict(r) for r in rows]

    # --- trades / apprentissages ----------------------------------------
    def log_trades(self, version: str, trades: list[Trade]) -> None:
        rows = [(version, t.side, str(t.entry_time), str(t.exit_time), t.entry, t.exit, t.size, t.pnl,
                 t.reason, ",".join(t.patterns), t.confidence) for t in trades]
        try:
            with self.db:
                self.db.executemany("INSERT INTO trades (version,side,entry_time,exit_time,entry,exit,size,pnl,"
                                    "reason,patterns,confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Ecriture des trades échouée : {exc}") from exc

    def pattern_stats(self, limit: int = 15) -> list[dict]:
        """Performance par setup (combinaison de patterns) : ce que « le trader » a appris."""
        rows = self.db.execute(
            "SELECT patterns, COUNT(*) AS n, ROUND(SUM(pnl),2) AS pnl, ROUND(AVG(pnl>0),3) AS win_rate "
            "FROM trades GROUP BY patterns ORDER BY n DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def add_learning(self, version: Optional[str], note: str) -> None:
        self._exec("INSERT INTO learnings (version,note,created_at) VALUES (?,?,?)", (version, note, _now()))

    def learnings(self) -> list[str]:
        return [r["note"] for r in self.db.execute("SELECT note FROM learnings ORDER BY id")]


def _finite(x: Any) -> Optional[float]:
    return float(x) if isinstance(x, (int, float)) and x == x and abs(x) != float("inf") else None
