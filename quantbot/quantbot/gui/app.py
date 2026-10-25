"""Application web locale (FastAPI) : API en LECTURE SEULE + interface terminal. Écoute uniquement sur 127.0.0.1 ; aucune route n'envoie d'ordre ni n'écrit d'approbation."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..ui import server as data
from ..ui.replay import list_strategies, run_strategy_replay
from .book import build_book
from .chart import chart_payload

STATIC = Path(__file__).parent / "static"
ROOT = Path(__file__).resolve().parents[2]
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1", "testserver"}


def create_app(root: Path = ROOT) -> FastAPI:
    app = FastAPI(title="quantbot", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0] if not (request.headers.get("host") or "").startswith("[") else "[::1]"
        if host not in LOCAL_HOSTS:                      # protection contre le « DNS rebinding » : seul l'accès local est servi
            return JSONResponse({"error": "hôte non autorisé"}, status_code=403)
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    def guarded(fn, *a):
        try:
            return fn(*a)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/health")
    def health():
        return {"ok": True, "read_only": True}

    @app.get("/api/state")
    def state():
        return data.collect_state(root)

    @app.get("/api/live")
    def live():
        return data.collect_live(root)

    @app.get("/api/paper")
    def paper(runner: Optional[str] = None):
        return data.collect_paper(root, runner)

    @app.get("/api/book")
    def book(period: str = Query("all", pattern="^(all|session|today)$")):
        return build_book(root, period)

    @app.get("/api/chart")
    def chart(runner: Optional[str] = None):
        return chart_payload(root, runner)

    @app.get("/api/strategies")
    def strategies():
        return list_strategies(root)

    @app.get("/api/strategy_replay")
    def strategy_replay(instrument: str, strategy: str = "orb", segment: str = "recherche", bars: int = 6000):
        return guarded(run_strategy_replay, instrument, bars, strategy, segment, root)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/", StaticFiles(directory=str(STATIC), html=False), name="static")
    return app
