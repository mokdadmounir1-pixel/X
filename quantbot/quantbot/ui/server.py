"""Interface locale (127.0.0.1 uniquement) : état du projet, résultats, calibration, données, rejeu d'un backtest.

Lecture seule sur les rapports et sur l'état du runtime (/api/live : SQLite en mode=ro). Le rejeu n'utilise QUE la période
de recherche (la période verrouillée n'est jamais lue). Cette interface n'envoie aucun ordre, n'écrit aucune approbation,
ne touche pas au coupe-circuit et ne se connecte pas au terminal.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).parent / "index.html"
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
    for name in SPEC_ORDER:
        spec = _read_json(root / "specs" / f"{name}.json")
        if spec is None:
            continue
        budget = spec.get("max_trials_budget", budget)
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
                            "diagnostics": r.get("diagnostics"), "costs": r.get("costs_used")})
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
    return {
        "status": {"live_trading": "AUCUN ordre n'est envoyé par cette interface (lecture seule)", "edge_validated": any(v == "PASS" for v in verdicts),
                   "mt5_broker": "quantbot/live écrit ; jamais exécuté d'ordre sur un terminal réel (seul un diagnostic en lecture seule, C1, a été fait)",
                   "registry_chain_ok": reg_ok, "trials": n_trials, "trials_budget": budget, "locked_reads": locked},
        "specs": specs,
        "battery": battery,
        "walkforward": walkforward,
        "daemon": _read_json(root / "data" / "live" / "DAEMON_STATUS.json"),
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


def collect_live(root: Path = ROOT) -> dict:
    """État du runtime en direct. LECTURE SEULE : SQLite en mode=ro, jamais de création de base, aucun appel au terminal."""
    state_path, kill_path, appr_path = _live_paths(root)
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
               symbol=kv.get("symbol"), mode=kv.get("mode", "NON_DEMARRE"), why=kv.get("why"), strategy=kv.get("strategy"),
               last_bar=kv.get("last_bar"), heartbeat_age_s=age, running=running,
               launcher_running_flag=kv.get("launcher_running"), stop_reason=kv.get("launcher_stop_reason"),
               intents=intents, events=events, paper_trades=trades,
               statistics_nature=("PAPER : prix MT5 réels, exécutions et PnL SIMULÉS — ce ne sont pas des fills réels"
                                  if kv.get("mode") == "OBSERVATION" else "ordres démo sous contrôles du broker" if kv.get("mode") == "DEMO_ACTIF" else None))
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


class Handler(BaseHTTPRequestHandler):
    root = ROOT

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, default=str, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                self._send(200, STATIC.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/state":
                self._json(collect_state(self.root))
            elif url.path == "/api/live":
                self._json(collect_live(self.root))
            elif url.path == "/api/replay":
                q = parse_qs(url.query)
                self._json(replay_instrument(q.get("instrument", [""])[0], int(q.get("bars", ["6000"])[0]),
                                             q.get("spec", ["baseline_v1"])[0], self.root))
            else:
                self._json({"error": "introuvable"}, 404)
        except (ValueError, KeyError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:  # pas de trace brute côté navigateur
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def log_message(self, *a) -> None:  # silence
        pass


def serve(port: int = 8790, root: Path = ROOT) -> None:
    Handler.root = root
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # JAMAIS 0.0.0.0
    print(f"quantbot UI : http://127.0.0.1:{port}/  (Ctrl+C pour arrêter)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
