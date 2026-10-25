"""Interface locale (127.0.0.1 uniquement) : état du projet, résultats, calibration, données, rejeu d'un backtest.

Lecture seule sur les rapports. Le rejeu n'utilise QUE la période de recherche (la période verrouillée n'est jamais lue)
et n'envoie aucun ordre : le trading réel est verrouillé.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).parent / "index.html"
SPEC_ORDER = ["baseline_v0", "baseline_v1", "v2_calibrated"]
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
    for name in SPEC_ORDER:
        spec = _read_json(root / "specs" / f"{name}.json")
        if spec is None:
            continue
        results = []
        for inst in spec.get("instruments", {}):
            r = _read_json(reports / name / f"{inst}.json")
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
    prov = _read_json(root / "data" / "real" / "PROVENANCE.json") or {}
    verdicts = [r.get("verdict") for s in specs for r in s["results"]]
    return {
        "status": {"live_trading": "VERROUILLÉ (aucun ordre ne peut partir)", "edge_validated": any(v == "PASS" for v in verdicts),
                   "mt5_broker": "écrit, testé uniquement contre un faux terminal", "registry_chain_ok": reg_ok,
                   "trials": n_trials, "trials_budget": 30, "locked_reads": locked, "tests": "voir README"},
        "specs": specs,
        "battery": battery,
        "data": [{k: i.get(k) for k in ("symbol", "rows", "start", "end", "span_years", "sha256")} for i in prov.get("instruments", [])],
        "data_notes": ["Horloge courtier : UTC+2 hiver / UTC+3 été, calendrier européen (reconstruite depuis time_broker_epoch).",
                       "Export plafonné à 80 000 barres par instrument : ce n'est pas tout l'historique.",
                       "Spread EURUSD inutilisable (44-83 % de zéros) : hypothèse déclarée dans la spec.",
                       "USTEC : trou réel de 55 jours (16 juil. -> 9 sept. 2025), géré (positions clôturées, ré-échauffement)."],
    }


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
                       for t in trades[-40:]]}


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
