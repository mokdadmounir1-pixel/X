"""Couche de DONNÉES de l'interface (état, résultats, simulations, rejeu) ; le serveur et l'interface sont dans quantbot/gui.

Lecture seule sur les rapports et sur l'état du runtime (/api/live : SQLite en mode=ro). Le rejeu n'utilise QUE la période
de recherche (la période verrouillée n'est jamais lue). Cette interface n'envoie aucun ordre, n'écrit aucune approbation,
ne touche pas au coupe-circuit et ne se connecte pas au terminal.
"""
from __future__ import annotations

import json
import os
from typing import Optional
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SPEC_ORDER = ["baseline_v0", "baseline_v1", "v2_calibrated", "mtf_v3", "inst_strategies_v1", "backward_v1"]
GLOB_SPECS = {"mtf_v3", "inst_strategies_v1", "backward_v1"}  # un fichier de résultat par essai : {instrument}_{timeframe|stratégie}.json
_cache: dict = {}
_lock = threading.Lock()


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def collect_state(root: Path = ROOT) -> dict:
    from ..lab.registry import TrialRegistry
    reports = root / "reports"
    reg_path = reports / "registry.jsonl"
    try:
        reg = TrialRegistry(reg_path) if reg_path.exists() else TrialRegistry()
        reg_ok, n_trials, locked = reg.verify(), reg.n_trials(), reg.locked_reads()
    except Exception:  # registre altéré
        reg_ok, n_trials, locked = False, 0, 0
    specs = []
    budget = None
    for f in sorted((root / "specs").glob("*.json")):          # budget déclaré = le plus élevé de TOUTES les specs (les anciennes gardent leur ancien chiffre)
        b = (_read_json(f) or {}).get("max_trials_budget")
        if isinstance(b, (int, float)):
            budget = max(budget or 0, int(b))
    b = (_read_json(root / "config" / "trial_budget.json") or {}).get("max_trials_budget")      # décision explicite de l'utilisateur : fait foi
    if isinstance(b, (int, float)):
        budget = max(budget or 0, int(b))
    for name in SPEC_ORDER:
        spec = _read_json(root / "specs" / f"{name}.json")
        if spec is None:
            continue
        budget = max(budget or 0, spec.get("max_trials_budget") or 0) or budget        # le budget déclaré le plus récent/élevé (les anciennes specs gardent leur 80)
        results = []
        if name in GLOB_SPECS:
            keys = [(f.stem, f) for f in sorted((reports / name).glob("*.json")) if not f.stem.endswith("_model")]
        else:
            keys = [(inst, reports / name / f"{inst}.json") for inst in spec.get("instruments", {})]
        for inst, path in keys:
            r = _read_json(path)
            if r is None:
                results.append({"instrument": inst, "status": "non exécuté"})
                continue
            ev = r["evaluation"]
            m = ev["metrics"]
            results.append({"instrument": inst, "verdict": ev["verdict"], "n_trades": m["n_trades"],
                            "expectancy_R": m["expectancy_R"], "profit_factor": m["profit_factor"],
                            "worst_trade_R": m.get("worst_trade_R"), "years": m.get("years"),
                            "gates": ev["gates"], "reason": ev["reason"], "n_trials": ev["n_trials"],
                            "diagnostics": r.get("diagnostics"), "costs": r.get("costs_used"),
                            "r_per_day": (m["expectancy_R"] * m["n_trades"] / (m["years"] * 252.0)) if m.get("years") and m.get("n_trades") else None})
        specs.append({"name": name, "parent": spec.get("parent"), "hypothesis": spec.get("hypothesis"),
                      "change_reason": spec.get("change_reason"), "results": results})
    battery = _read_json(reports / "battery_v1" / "summary.json")
    walkforward = []
    for wf_dir in sorted(reports.glob("wf_*")):
        if wf_dir.is_dir():
            for f in sorted(wf_dir.glob("*.json")):
                r = _read_json(f)
                if r:
                    walkforward.append({"spec": wf_dir.name, **{k: r.get(k) for k in ("instrument", "strategy", "n_configs", "walk", "summary", "windows")}})
    prov = _read_json(root / "data" / "real" / "PROVENANCE.json") or {}
    verdicts = [r.get("verdict") for s in specs for r in s["results"]]
    from .replay import objective as _objective
    obj = _objective(root)
    rows = [{"spec": sp["name"], "name": r["instrument"], "verdict": r["verdict"], "n_trades": r["n_trades"], "expectancy_R": r["expectancy_R"], "years": r["years"], "r_per_day": r["r_per_day"]}
            for sp in specs for r in sp["results"] if r.get("r_per_day") is not None]
    for x in rows:   # un R/jour élevé qui n'est que du bêta de marché n'est PAS un avantage : on le signale et on l'exclut de la référence
        for prefix, why in obj["beta_flags"].items():
            if f"{x['spec']}:{x['name']}".startswith(prefix):
                x["beta"] = why
    rows.sort(key=lambda x: -x["r_per_day"])
    honest = [x for x in rows if not x.get("beta")]
    obj["best"] = honest[0] if honest else None
    obj["rows"] = rows[:14]
    obj["multiple_of_best"] = (obj["target_r_per_day"] / honest[0]["r_per_day"]) if honest and honest[0]["r_per_day"] > 0 else None
    return {
        "status": {"live_trading": "AUCUN ordre n'est envoyé par cette interface (lecture seule)", "edge_validated": any(v == "PASS" for v in verdicts),
                   "mt5_broker": "quantbot/live écrit ; jamais exécuté d'ordre sur un terminal réel (seul un diagnostic en lecture seule, C1, a été fait)",
                   "registry_chain_ok": reg_ok, "trials": n_trials, "trials_budget": budget, "locked_reads": locked},
        "specs": specs,
        "battery": battery,
        "walkforward": walkforward,
        "objective": obj,
        "daemon": _read_json(root / "data" / "live" / "DAEMON_STATUS.json"),
        "sync": _read_json(root / "data" / "sync_status.json"),
        "supervisor": _read_json(root / "runtime" / "supervisor.json"),
        "queue": _read_json(reports / "QUEUE_STATUS.json"),
        "data": [{k: i.get(k) for k in ("symbol", "rows", "start", "end", "span_years", "sha256")} for i in prov.get("instruments", [])],
        "data_notes": ["Horloge courtier : UTC+2 hiver / UTC+3 été, calendrier européen (reconstruite depuis time_broker_epoch).",
                       "Export plafonné à 80 000 barres par instrument : ce n'est pas tout l'historique.",
                       "Spread EURUSD inutilisable (44-83 % de zéros) : hypothèse déclarée dans la spec.",
                       "USTEC : trou réel de 55 jours (16 juil. -> 9 sept. 2025), géré (positions clôturées, ré-échauffement)."],
    }


def _live_paths(root: Path) -> tuple[Path, Path, Path]:
    state = Path(os.environ.get("QUANTBOT_STATE") or root / "runtime" / "live_state.db")
    kill = Path(os.environ.get("QUANTBOT_KILL") or state.parent / "KILL")
    appr = Path(os.environ.get("QUANTBOT_APPROVALS") or root / "approved_strategies.json")
    return state, kill, appr


def collect_live(root: Path = ROOT, state_override: Optional[Path] = None) -> dict:
    """État du runtime en direct. LECTURE SEULE : SQLite en mode=ro, jamais de création de base, aucun appel au terminal."""
    state_path, kill_path, appr_path = _live_paths(root)
    if state_override is not None:
        state_path, kill_path = state_override, state_override.parent / "KILL"
    out: dict = {"available": False, "state_path": str(state_path), "kill_file_present": kill_path.exists(),
                 "approvals": _approvals_summary(appr_path), "kill_reasons": [], "intents": [], "events": [], "paper_trades": []}
    if kill_path.exists():
        out["kill_reasons"].append(f"fichier {kill_path.name} présent")
    if not state_path.is_file():
        out["note"] = "Aucune base d'état : le lanceur n'a jamais tourné avec ce chemin."
        return out
    conn = sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        kv = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key,value FROM kv")}
        intents = [dict(r) for r in conn.execute("SELECT id,created,updated,kind,side,status,detail,ticket,strategy FROM intents ORDER BY created DESC LIMIT 20")]
        events = [dict(r) for r in conn.execute("SELECT ts,level,kind,detail FROM events ORDER BY id DESC LIMIT 30")]
        trades = []
        for r in conn.execute("SELECT ts,detail FROM events WHERE kind='trade' ORDER BY id DESC LIMIT 50"):
            try:
                trades.append({"ts": r["ts"], **json.loads(r["detail"])})
            except (json.JSONDecodeError, TypeError):
                continue
    finally:
        conn.close()
    open_intents = [i for i in intents if i["status"] in ("PENDING", "SENT", "UNKNOWN")]
    if kv.get("kill"):
        out["kill_reasons"].append(f"déclenché : {kv['kill']}")
    if open_intents:
        out["kill_reasons"].append(f"{len(open_intents)} intention(s) non rapprochée(s)")
    hb = kv.get("heartbeat")
    age = time.time() - hb if isinstance(hb, (int, float)) else None
    running = bool(kv.get("launcher_running")) and age is not None and age < 60
    out.update(available=True, bars=kv.get("bars") or [], position=kv.get("position"), pending=kv.get("pending"),
               symbol=kv.get("symbol"), source=kv.get("source"), mode=kv.get("mode", "NON_DEMARRE"), why=kv.get("why"), strategy=kv.get("strategy"),
               last_bar=kv.get("last_bar"), heartbeat_age_s=age, running=running,
               launcher_running_flag=kv.get("launcher_running"), stop_reason=kv.get("launcher_stop_reason"),
               intents=intents, events=events, paper_trades=trades,
               statistics_nature=("PAPER : prix MT5 réels, exécutions et PnL SIMULÉS — ce ne sont pas des fills réels"
                                  if kv.get("mode") == "OBSERVATION" else "ordres démo sous contrôles du broker" if kv.get("mode") == "DEMO_ACTIF" else None))
    return out


def collect_paper(root: Path = ROOT, runner: Optional[str] = None) -> dict:
    """Agrège les simulations PAPER (runtime/paper/*.db) : une ligne par couple instrument x stratégie. Lecture seule."""
    d = Path(os.environ.get("QUANTBOT_PAPER") or root / "runtime" / "paper")
    target = (_read_json(root / "specs" / "objective.json") or {}).get("target_r_per_day", 0.33)
    out = {"available": False, "dir": str(d), "runners": [], "target_r_per_day": target, "status": _read_json(d / "STATUS.json")}
    if not d.is_dir():
        out["note"] = "Aucune simulation : lancer scripts/paper_all.py (ou scripts\\start_all.bat)."
        return out
    now = time.time()
    for db in sorted(d.glob("*.db")):
        L = collect_live(root, db)
        if not L.get("available"):
            continue
        trades = [t for t in L["paper_trades"]]
        rs = [t["r"] for t in trades if t.get("r") is not None]
        first = min([e["ts"] for e in L["events"]] + [t["ts"] for t in trades] or [now])
        days = max(1.0, np.busday_count(pd.Timestamp(first, unit="s").date(), pd.Timestamp(now, unit="s").date()) + 1)
        out["runners"].append({"id": db.stem, "symbol": L.get("symbol"), "mode": L["mode"], "running": L["running"], "last_bar": L["last_bar"], "heartbeat_age_s": L["heartbeat_age_s"],
                               "position": L["position"], "pending": L["pending"], "n_trades": len(rs), "total_R": float(sum(rs)), "avg_R": float(np.mean(rs)) if rs else None,
                               "r_per_day": float(sum(rs)) / days, "since": first, "kill": L["kill_reasons"], "source": (L.get("source") or "MT5")})
    out["available"] = bool(out["runners"])
    tot = sum(r["total_R"] for r in out["runners"])
    out["total_R"] = tot
    out["selected"] = None
    pick = runner or (out["runners"][0]["id"] if out["runners"] else None)
    if pick and (d / f"{pick}.db").exists() and "/" not in pick and "\\" not in pick and ".." not in pick:
        out["selected"] = {"id": pick, **collect_live(root, d / f"{pick}.db")}
    return out


def _approvals_summary(path: Path) -> dict:
    if not path.is_file():
        return {"present": False, "entries": [], "note": "aucune approbation : le bot reste en OBSERVATION"}
    data = _read_json(path)
    try:
        entries = [{k: e.get(k) for k in ("id", "instrument", "spec", "approved_by", "date")} for e in data["approved"]]
    except (KeyError, TypeError, AttributeError):
        return {"present": True, "entries": [], "note": "fichier illisible : traité comme absent par le bot"}
    return {"present": True, "entries": entries, "note": "approbations humaines (l'interface n'en écrit jamais)"}


def run_replay(df: pd.DataFrame, settings, max_points: int = 500) -> dict:
    from ..backtest.engine import Backtester
    res = Backtester(settings).run(df)
    eq = res.equity_curve
    step = max(1, len(eq) // max_points)
    eq = eq.iloc[::step]
    trades = res.trades
    return {"metrics": {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in res.metrics.items()},
            "n_signals": res.n_signals, "rejections": res.rejections,
            "equity": [[str(t), float(v)] for t, v in zip(eq.index, eq.to_numpy())],
            "reasons": {k: sum(1 for t in trades if t.reason == k) for k in sorted({t.reason for t in trades})},
            "trades": [{"t": str(t.entry_time), "side": t.side, "reason": t.reason, "r_nominal": round(t.r_nominal, 3)}
                       for t in trades[-40:]],
            # graphique des prix de la fenêtre rejouée + chaque trade (entrée -> sortie), pour LIRE ce que fait la stratégie
            "price": [[str(t), float(v)] for t, v in zip(df.index[::max(1, len(df) // 600)], df["close"].to_numpy()[::max(1, len(df) // 600)])],
            "markers": [{"t0": str(t.entry_time), "p0": float(t.entry), "t1": str(t.exit_time), "p1": float(t.exit),
                         "side": t.side, "r": round(t.r_nominal, 3), "reason": t.reason} for t in trades[-300:]]}


def replay_instrument(instrument: str, bars: int, spec_name: str = "baseline_v1", root: Path = ROOT) -> dict:
    from ..data.mt5 import costs_from_frame, load_mt5_csv
    from ..lab.locked import split_locked
    from ..lab.specs import build_settings
    spec = _read_json(root / "specs" / f"{spec_name}.json")
    if spec is None or instrument not in spec["instruments"]:
        raise ValueError("instrument ou spec inconnu")
    bars = max(500, min(int(bars), 20000))
    key = (instrument, bars, spec_name)
    with _lock:
        if key in _cache:
            return _cache[key]
    df = load_mt5_csv(root / "data" / "real" / spec["instruments"][instrument])
    research, _locked = split_locked(df, spec["lock_months"], spec["lock_min_frac"])  # la période verrouillée n'est jamais renvoyée
    seg = research.iloc[-bars:]
    settings = build_settings(spec, instrument, costs_from_frame(df), research)
    out = run_replay(seg, settings)
    ref = _read_json(root / "reports" / spec_name / f"{instrument}.json")
    ev = (ref or {}).get("evaluation")
    out["reference"] = None if ev is None else {"verdict": ev["verdict"], "n_trades": ev["metrics"]["n_trades"],
                                                "expectancy_R": ev["metrics"]["expectancy_R"], "profit_factor": ev["metrics"]["profit_factor"],
                                                "years": ev["metrics"].get("years")}
    out["buy_hold_return"] = float(seg["close"].iloc[-1] / seg["close"].iloc[0] - 1.0)
    out.update({"instrument": instrument, "spec": spec_name, "bars": len(seg), "start": str(seg.index[0]),
                "end": str(seg.index[-1]), "note": "Rejeu sur la période de RECHERCHE uniquement. Aucun ordre n'est envoyé."})
    with _lock:
        _cache[key] = out
    return out
