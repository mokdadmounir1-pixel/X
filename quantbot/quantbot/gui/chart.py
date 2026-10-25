"""Charge utile des graphiques temps réel : bougies clôturées publiées par le lanceur, position / ordre en attente, trades clos et zones Order Block / FVG (SMC)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from ..ui.replay import zones_payload
from .book import read_db, runner_dbs


def _epoch(s) -> int:
    t = pd.Timestamp(str(s))
    return int(t.value // 10**9) if t.tzinfo is None else int(t.tz_convert("UTC").value // 10**9)


def chart_payload(root: Path, runner: Optional[str]) -> dict:
    dbs = {rid: (p, k) for rid, p, k in runner_dbs(root)}
    if not dbs:
        return {"available": False, "note": "Aucune simulation en cours : lancer scripts/paper_all.py."}
    rid = runner if runner in dbs else sorted(dbs)[0]
    db = read_db(dbs[rid][0])
    if db is None:
        return {"available": False, "note": "Base illisible."}
    kv = db["kv"]
    bars = kv.get("bars") or []
    out = {"available": True, "runner": rid, "runners": sorted(dbs), "symbol": kv.get("symbol"), "strategy": kv.get("strategy"), "mode": kv.get("mode"), "source": kv.get("source") or "MT5",
           "last_bar": kv.get("last_bar"), "position": kv.get("position"), "pending": kv.get("pending"), "risk": kv.get("risk"),
           "candles": [{"time": _epoch(b[0]), "open": b[1], "high": b[2], "low": b[3], "close": b[4], "volume": b[5] if len(b) > 5 else 0.0} for b in bars], "trades": [], "zones": []}
    for e in db["trades"]:
        try:
            d = json.loads(e["detail"])
        except json.JSONDecodeError:
            continue
        if d.get("entry_time") and out["candles"] and _epoch(d["exit_time"]) >= out["candles"][0]["time"]:
            out["trades"].append({"side": d["side"], "t0": _epoch(d["entry_time"]), "t1": _epoch(d["exit_time"]), "entry": d["entry"], "exit": d["exit"], "sl": d.get("stop"), "tp": d.get("tp"),
                                  "r": d.get("r"), "reason": d.get("reason")})
    strat = kv.get("strategy") or ""
    if strat.startswith("smc") and len(bars) > 100:
        spec = None
        for cand in (kv.get("spec"), "smc_v1.json"):
            p = root / "specs" / (cand or "")
            if cand and p.is_file():
                spec = json.loads(p.read_text(encoding="utf-8")); break
        scfg = ((spec or {}).get("strategies") or {}).get(strat)
        if scfg:
            from ..strategies import smc
            df = pd.DataFrame({"open": [b[1] for b in bars], "high": [b[2] for b in bars], "low": [b[3] for b in bars], "close": [b[4] for b in bars], "volume": [b[5] if len(b) > 5 else 0.0 for b in bars]},
                              index=pd.DatetimeIndex([pd.Timestamp(str(b[0])).tz_localize(None) if pd.Timestamp(str(b[0])).tzinfo else pd.Timestamp(str(b[0])) for b in bars]))
            try:
                out["zones"] = zones_payload(smc.zones(df, scfg["rule"], scfg["params"]), df.index[-1])
            except Exception as exc:     # une zone illisible ne doit pas casser le graphique
                out["zones_error"] = f"{type(exc).__name__}: {exc}"
    return out
