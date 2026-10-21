"""Zero-dependency dashboard server: python -m quantlab dashboard --port 8767"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..tools.install import load_status

HERE = Path(__file__).parent
RES = Path(__file__).resolve().parents[2] / "results" / "latest.json"


def make_handler(session):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            p = self.path.split("?")[0]
            if p in ("/", "/index.html"):
                b = (HERE / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
            elif p == "/api/state":
                self._json(session.snapshot())
            elif p == "/api/research":
                self._json(json.loads(RES.read_text()) if RES.exists() else {"reports": []})
            elif p == "/api/tools":
                self._json(load_status())
            elif p == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                from collections import deque
                q = deque(maxlen=500)
                session.subs.append(q)
                try:
                    while True:
                        while q:
                            self.wfile.write(f"data: {json.dumps(q.popleft())}\n\n".encode())
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        time.sleep(0.25)
                except Exception:
                    pass
                finally:
                    session.subs.remove(q)
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if self.path == "/api/control":
                n = int(self.headers.get("Content-Length", 0))
                d = json.loads(self.rfile.read(n) or b"{}")
                if "speed" in d:
                    session.speed = float(d["speed"])
                if "paused" in d:
                    session.paused = bool(d["paused"])
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)

    return H


def serve(session, host="127.0.0.1", port=8767):
    session.thread.start()
    srv = ThreadingHTTPServer((host, port), make_handler(session))
    print(f"dashboard on http://{host}:{port}")
    srv.serve_forever()
