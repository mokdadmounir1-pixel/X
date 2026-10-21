"""Journal SQLite de chaque décision et de chaque trade."""
from __future__ import annotations
import json
import sqlite3
import threading


class Journal:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, t INTEGER, agent TEXT, sym TEXT, type TEXT, data TEXT);
        CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, agent TEXT, sym TEXT, side INTEGER, entry_t INTEGER,
            exit_t INTEGER, entry REAL, exit REAL, lots REAL, r REAL, pnl REAL, reason TEXT, grade INTEGER);
        CREATE TABLE IF NOT EXISTS fills(id INTEGER PRIMARY KEY, t INTEGER, agent TEXT, sym TEXT, requested REAL,
            executed REAL, slippage REAL, status TEXT);
        """)

    def decision(self, t, agent, sym, typ, data):
        with self.lock:
            self.db.execute("INSERT INTO decisions(t,agent,sym,type,data) VALUES(?,?,?,?,?)",
                            (int(t), agent, sym, typ, json.dumps(data, default=float)))
            self.db.commit()

    def trade(self, agent, tr: dict):
        with self.lock:
            self.db.execute("INSERT INTO trades(agent,sym,side,entry_t,exit_t,entry,exit,lots,r,pnl,reason,grade) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (agent, tr["sym"], int(tr["side"]), int(tr["entry_t"]), int(tr["exit_t"]), float(tr["entry"]),
                             float(tr["exit"]), float(tr["lots"]), float(tr["r"]), float(tr["pnl"]), tr["reason"], int(tr["grade"])))
            self.db.commit()

    def fill(self, t, agent, sym, requested, executed, status):
        with self.lock:
            self.db.execute("INSERT INTO fills(t,agent,sym,requested,executed,slippage,status) VALUES(?,?,?,?,?,?,?)",
                            (int(t), agent, sym, requested, executed, executed - requested, status))
            self.db.commit()

    def trades(self, agent=None):
        with self.lock:
            q = "SELECT agent,sym,side,entry_t,exit_t,entry,exit,lots,r,pnl,reason,grade FROM trades" + \
                (" WHERE agent=?" if agent else "") + " ORDER BY id"
            return self.db.execute(q, (agent,) if agent else ()).fetchall()
