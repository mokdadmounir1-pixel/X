"""Serveur HTTP standard (sans CDN ni Node) : page statique + API JSON."""
from __future__ import annotations
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

STATIC = Path(__file__).parent / "static"


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
                return self._send(200, json.dumps(st, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
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
