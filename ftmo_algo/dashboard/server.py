"""Serveur HTTP standard (sans CDN ni Node) : page statique + API JSON."""
from __future__ import annotations
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

STATIC = Path(__file__).parent / "static"


def clean(o):
    """JSON strict : NaN/Inf -> null, types numpy -> natifs."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        try:
            o = o.item()
        except Exception:
            return str(o)
    if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
        return None
    return o


def _evolution(d):
    """Résumé de l'amélioration continue (fichiers écrits par `python -m ftmo_algo evolve`) + 25 derniers changements."""
    if not d:
        return {"present": False}
    d = Path(d)
    f = d / "evolution_summary.json"
    if not f.exists():
        return {"present": False}
    out = {"present": True, **json.loads(f.read_text())}
    jf = d / "evolution_journal.jsonl"
    if jf.exists():
        rows = [json.loads(x) for x in jf.read_text().splitlines() if x.strip()]
        out["journal"] = [r for r in rows if r["event"] not in ("INSIGHT", "PROBATION_OK")][-25:]
    cf = d / "evolved_config.json"
    if cf.exists():
        out["config"] = json.loads(cf.read_text())
    return out


def make_handler(runner):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body if isinstance(body, bytes) else body.encode())

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html")
            if u.path == "/api/state":
                q = parse_qs(u.query)
                st = runner.state(q.get("symbol", [None])[0], q.get("tf", ["M15"])[0])
                return self._send(200, json.dumps(clean(st), default=str, allow_nan=False))
            if u.path == "/api/evolution":
                return self._send(200, json.dumps(clean(_evolution(getattr(runner, "evo_dir", None))), default=str, allow_nan=False))
            if u.path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            return self._send(404, "{}")

        def do_POST(self):
            if urlparse(self.path).path == "/api/control":
                n = int(self.headers.get("Content-Length", 0))
                d = json.loads(self.rfile.read(n) or b"{}")
                if "pause" in d:
                    runner.paused = bool(d["pause"])
                if "speed" in d:
                    runner.speed = max(0.0, float(d["speed"]))
                return self._send(200, json.dumps({"paused": runner.paused, "speed": runner.speed}))
            return self._send(404, "{}")
    return H


def serve(runner, port=8767, host="127.0.0.1", block=True):
    srv = ThreadingHTTPServer((host, port), make_handler(runner))
    if block:
        srv.serve_forever()
    else:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
