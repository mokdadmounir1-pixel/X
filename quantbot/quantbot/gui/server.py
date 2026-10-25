"""Lancement du terminal : uvicorn lié à 127.0.0.1 UNIQUEMENT (jamais 0.0.0.0)."""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import uvicorn

from .app import ROOT, create_app

HOST = "127.0.0.1"


def free_port(preferred: int = 8790) -> int:
    for port in (preferred, *range(preferred + 1, preferred + 40)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port)); return port
            except OSError:
                continue
    raise OSError("aucun port local libre")


def serve(port: int = 8790, root: Path = ROOT) -> None:
    port = free_port(port)
    print(f"quantbot terminal : http://{HOST}:{port}/  (Ctrl+C pour arrêter)")
    uvicorn.run(create_app(root), host=HOST, port=port, log_level="warning")


def start_background(port: int = 8790, root: Path = ROOT) -> tuple[int, uvicorn.Server]:
    """Démarre le serveur dans un thread (fenêtre de bureau) et attend qu'il réponde."""
    port = free_port(port)
    server = uvicorn.Server(uvicorn.Config(create_app(root), host=HOST, port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return port, server
        time.sleep(0.1)
    raise RuntimeError("le serveur local n'a pas démarré")
