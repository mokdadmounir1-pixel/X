"""Livre de trades et attribution par stratégie : agrège les bases d'état des simulations PAPER (runtime/paper/*.db) et du lanceur (QUANTBOT_STATE). LECTURE SEULE.

Honnêteté des champs : `recorded_ms` est l'horloge du programme à l'enregistrement (milliseconde) ; `entry_time`/`exit_time` sont les heures des BARRES (le moteur décide à la clôture
d'une barre et exécute à l'ouverture suivante : une précision « milliseconde » de l'exécution n'existerait que pour un vrai fill). PnL latent = dernière clôture publiée.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..strategies.build import strategy_code

STATUS_LABEL = {"take_profit": "TP", "stop_loss": "SL", "max_hold": "TEMPS", "weekend": "WEEK-END", "ftmo_weekend": "WEEK-END", "data_gap": "TROU DONNÉES",
                "active_risk_flatten": "RISQUE ACTIF", "end_of_data": "FIN"}
CAPITAL_PER_RUNNER = 100_000.0


def _paper_dir(root: Path) -> Path:
    return Path(os.environ.get("QUANTBOT_PAPER") or root / "runtime" / "paper")


def runner_dbs(root: Path) -> list[tuple[str, Path, str]]:
    out = [(p.stem, p, "paper") for p in sorted(_paper_dir(root).glob("*.db"))] if _paper_dir(root).is_dir() else []
    live = Path(os.environ.get("QUANTBOT_STATE") or root / "runtime" / "live_state.db")
    if live.is_file():
        out.append(("live:" + live.stem, live, "live"))
    return out


def read_db(path: Path) -> Optional[dict]:
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    except sqlite3.Error:
        return None
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        kv = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key,value FROM kv")}
        ev = [dict(r) for r in conn.execute("SELECT id,ts,detail FROM events WHERE kind='trade' ORDER BY id")]
        ign = [dict(r) for r in conn.execute("SELECT id,ts,detail FROM events WHERE kind='ignored' ORDER BY id")]
        return {"kv": kv, "trades": ev, "ignored": ign}
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _row_closed(runner: str, kind: str, e: dict, kv: dict) -> Optional[dict]:
    try:
        d = json.loads(e["detail"])
    except (json.JSONDecodeError, TypeError):
        return None
    strat = d.get("strategy") or kv.get("strategy") or "?"
    sign = 1.0 if d.get("side") == "long" else -1.0
    return {"id": f"{runner}#{e['id']}", "runner": runner, "kind": kind, "status": STATUS_LABEL.get(d.get("reason"), str(d.get("reason", "")).upper()), "open": False,
            "recorded_ms": int(d.get("recorded_ms") or e["ts"] * 1000), "strategy": strat, "strategy_code": strategy_code(strat), "symbol": d.get("symbol") or kv.get("symbol"),
            "side": d.get("side"), "entry_time": d.get("entry_time"), "exit_time": d.get("exit_time") or d.get("t"), "entry": d.get("entry"), "exit": d.get("exit"),
            "sl": d.get("stop"), "tp": d.get("tp"), "size": d.get("size"), "pnl": d.get("pnl"), "r": d.get("r"), "reason": d.get("reason"), "paper": d.get("paper", True),
            "source": kv.get("source") or "MT5", "dir": sign}


def _row_open(runner: str, kind: str, kv: dict) -> Optional[dict]:
    pos = kv.get("position")
    if not pos:
        return None
    bars = kv.get("bars") or []
    last = bars[-1][4] if bars else None
    sign = 1.0 if pos["side"] == "long" else -1.0
    pnl = (last - pos["entry"]) * pos["size"] * sign if last is not None else None
    dist = abs(pos["entry"] - pos["stop"]) or None
    r = ((last - pos["entry"]) * sign / dist) if (last is not None and dist) else None
    return {"id": f"{runner}#open", "runner": runner, "kind": kind, "status": "OUVERT", "open": True, "recorded_ms": int(kv.get("position_ts_ms") or 0),
            "strategy": pos.get("strategy") or kv.get("strategy"), "strategy_code": strategy_code(pos.get("strategy") or kv.get("strategy") or "?"),
            "symbol": pos.get("symbol") or kv.get("symbol"), "side": pos["side"], "entry_time": pos["entry_time"], "exit_time": None, "entry": pos["entry"], "exit": last,
            "sl": pos["stop"], "tp": pos["tp"], "size": pos["size"], "pnl": pnl, "r": r, "reason": None, "paper": kv.get("mode") != "DEMO_ACTIF", "source": kv.get("source") or "MT5", "dir": sign}


def build_book(root: Path, period: str = "all", now: Optional[float] = None) -> dict:
    now = now or time.time()
    rows, runners, started, ignored = [], [], [], []
    for rid, path, kind in runner_dbs(root):
        db = read_db(path)
        if db is None:
            continue
        kv = db["kv"]
        runners.append({"id": rid, "kind": kind, "symbol": kv.get("symbol"), "strategy": kv.get("strategy"), "strategy_code": strategy_code(kv.get("strategy") or "?"), "mode": kv.get("mode"),
                        "source": kv.get("source") or "MT5", "last_bar": kv.get("last_bar"), "risk": kv.get("risk"), "heartbeat": kv.get("heartbeat"),
                        "running": bool(kv.get("launcher_running")) or (kv.get("heartbeat") is not None and now - float(kv["heartbeat"]) < 90)})
        for e in db.get("ignored", []):
            try:
                d = json.loads(e["detail"]); d["runner"] = rid; d["id"] = f"{rid}!{e['id']}"; ignored.append(d)
            except (json.JSONDecodeError, TypeError):
                pass
        for e in db["trades"]:
            r = _row_closed(rid, kind, e, kv)
            if r:
                rows.append(r)
        o = _row_open(rid, kind, kv)
        if o:
            rows.append(o)
        if db["trades"]:
            started.append(db["trades"][0]["ts"])
    st = None
    try:
        st = json.loads((_paper_dir(root) / "STATUS.json").read_text(encoding="utf-8")).get("started")
    except (OSError, json.JSONDecodeError):
        pass
    session_start = float(st) if st else (min(started) if started else now)
    if period == "today":
        day0 = pd.Timestamp(now, unit="s").normalize().timestamp()
        rows = [r for r in rows if r["open"] or (r["recorded_ms"] / 1000.0) >= day0]
    elif period == "session":
        rows = [r for r in rows if r["open"] or (r["recorded_ms"] / 1000.0) >= session_start]
    rows.sort(key=lambda r: (r["recorded_ms"], r["id"]), reverse=True)
    return {"rows": rows, "runners": runners, "metrics": metrics(rows, max(len(runners), 1)), "ignored": ignored_summary(ignored), "by_strategy": by_strategy(rows), "curve": curve(rows),
            "period": period, "session_start": session_start, "now": now,
            "note": "PnL latent = dernière clôture publiée. Heures d'entrée/sortie = barres ; « enregistré » = horloge du programme (ms). Trades PAPER : exécutions simulées."}


def ignored_summary(rows: list) -> dict:
    """Signaux IGNORÉS (position déjà ouverte, arrêt de risque, hors séance...) et ce qu'ils auraient donné (contrefactuel indicatif, coûts déduits, positions superposées)."""
    def agg(rs):
        r = np.array([float(x["r"]) for x in rs], dtype=float)
        return {"n": int(len(r)), "sum_r": float(r.sum()) if len(r) else 0.0, "mean_r": float(r.mean()) if len(r) else None, "win_rate": float((r > 0).mean()) if len(r) else None}
    by_reason, by_strategy = {}, {}
    for x in rows:
        by_reason.setdefault(x.get("reason") or "?", []).append(x); by_strategy.setdefault(strategy_code(x.get("strategy") or "?"), []).append(x)
    return {"total": agg(rows), "by_reason": {k: agg(v) for k, v in sorted(by_reason.items())}, "by_strategy": {k: agg(v) for k, v in sorted(by_strategy.items())},
            "rows": sorted(rows, key=lambda x: x.get("recorded_ms", 0), reverse=True)[:200],
            "note": "Contrefactuel : chaque signal ignoré est suivi sur les barres suivantes (entrée à l'ouverture suivante, stop prioritaire, coûts déduits). Indicatif : positions superposées, taille non simulée, aucune influence sur les décisions."}


def win_profile(rs) -> dict:
    """Taux de réussite lu AVEC son contexte : R:R réalisé (gain moyen / perte moyenne) et taux d'équilibre 1/(1+R:R). Un taux élevé avec un R:R faible ne prouve rien."""
    rs = [float(x) for x in rs if x is not None]
    wins, losses = [x for x in rs if x > 0], [x for x in rs if x <= 0]
    out = {"avg_win_r": float(np.mean(wins)) if wins else None, "avg_loss_r": float(np.mean(losses)) if losses else None, "realised_rr": None, "breakeven_wr": None, "wr_edge": None}
    if wins and losses and np.mean(losses) < 0:
        rr = float(np.mean(wins) / -np.mean(losses)); out["realised_rr"] = rr; out["breakeven_wr"] = 1.0 / (1.0 + rr)
        out["wr_edge"] = len(wins) / len(rs) - out["breakeven_wr"]
    return out


def metrics(rows: list, n_runners: int) -> dict:
    closed = [r for r in rows if not r["open"] and r["pnl"] is not None]
    openr = [r for r in rows if r["open"]]
    realized = float(sum(r["pnl"] for r in closed))
    unreal = float(sum(r["pnl"] or 0.0 for r in openr))
    rs = [r["r"] for r in closed if r["r"] is not None]
    cap = CAPITAL_PER_RUNNER                       # UN SEUL compte FTMO simulé de 100 000 $ (comme le registre de risque) : tous les lanceurs trades sur ce même compte, jamais 100 000 $ chacun
    open_risk = float(sum(abs((r.get("entry") or 0.0) - (r.get("sl") or 0.0)) * (r.get("size") or 0.0) for r in openr))
    seq = sorted(closed, key=lambda r: (str(r["exit_time"]), r["recorded_ms"]))
    eq = np.cumsum([0.0] + [r["pnl"] for r in seq]) if seq else np.array([0.0])
    peak = float(eq.max()); cur = float(eq[-1] + unreal)
    dd_money = max(0.0, peak - cur)
    out = {"n_closed": len(closed), "n_open": len(openr), "pnl_realized": realized, "pnl_unrealized": unreal, "pnl_total": realized + unreal, "r_total": float(sum(rs)),
           "drawdown_money": dd_money, "drawdown_pct": dd_money / cap if cap else 0.0, "capital": cap, "equity": cap + realized + unreal, "n_runners": n_runners, "capital_if_independent": cap * n_runners, "open_risk": open_risk, "open_risk_pct": open_risk / cap, "win_rate": (sum(1 for r in closed if r["pnl"] > 0) / len(closed)) if closed else None,
           "avg_r": float(np.mean(rs)) if rs else None, "sharpe": None, "sharpe_days": 0,
           **win_profile(rs), "sharpe_note": "Sharpe annualisé sur les PnL journaliers (jours ouvrés, jours sans trade = 0) ; non affiché sous 20 jours."}
    if closed:
        d = pd.Series([r["pnl"] for r in closed], index=pd.to_datetime([str(r["exit_time"])[:10] for r in closed])).groupby(level=0).sum()
        days = pd.bdate_range(d.index.min(), d.index.max())
        d = d.reindex(days, fill_value=0.0) / cap
        out["sharpe_days"] = int(len(d))
        if len(d) >= 20 and d.std() > 0:
            out["sharpe"] = float(d.mean() / d.std() * np.sqrt(252))
    return out


def by_strategy(rows: list) -> list:
    g: dict = {}
    for r in rows:
        a = g.setdefault(r["strategy_code"], {"strategy_code": r["strategy_code"], "n": 0, "open": 0, "wins": 0, "r": 0.0, "pnl": 0.0, "_rs": []})
        if r["open"]:
            a["open"] += 1; a["pnl"] += r["pnl"] or 0.0
        elif r["pnl"] is not None:
            a["n"] += 1; a["wins"] += int(r["pnl"] > 0); a["r"] += r["r"] or 0.0; a["pnl"] += r["pnl"]; a["_rs"].append(r["r"])
    out = []
    for a in g.values():
        a["win_rate"] = a["wins"] / a["n"] if a["n"] else None
        a["avg_r"] = a["r"] / a["n"] if a["n"] else None
        a.update(win_profile(a.pop("_rs")))
        out.append(a)
    return sorted(out, key=lambda a: -a["pnl"])


def curve(rows: list) -> list:
    """PnL cumulé réalisé par strategy_code, point par trade clos : [{strategy_code, points:[[exit_time, cum_pnl], ...]}, + TOTAL]."""
    closed = sorted([r for r in rows if not r["open"] and r["pnl"] is not None], key=lambda r: (str(r["exit_time"]), r["recorded_ms"]))
    series: dict = {"TOTAL": []}
    cum: dict = {}
    tot = 0.0
    for r in closed:
        k = r["strategy_code"]
        cum[k] = cum.get(k, 0.0) + r["pnl"]; tot += r["pnl"]
        series.setdefault(k, []).append([str(r["exit_time"]), cum[k]]); series["TOTAL"].append([str(r["exit_time"]), tot])
    return [{"strategy_code": k, "points": v} for k, v in series.items()]
