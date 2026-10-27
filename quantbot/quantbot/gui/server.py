"""Lancement du terminal : uvicorn lié à 127.0.0.1 UNIQUEMENT (jamais 0.0.0.0)."""
from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from .app import ROOT, create_app

HOST = "127.0.0.1"
DEFAULT_PORT = 3214      # port DÉDIÉ à quantbot (évite 8000/8080/8790… souvent pris par d'autres projets) ; surcharge : variable QUANTBOT_PORT ou --port


def configured_port(port: int | None = None) -> int:
    if port:
        return int(port)
    try:
        return int(os.environ.get("QUANTBOT_PORT") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def free_port(preferred: int = DEFAULT_PORT) -> int:
    for port in (preferred, *range(preferred + 1, preferred + 40)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port)); return port
            except OSError:
                continue
    raise OSError("aucun port local libre")


def write_port_file(root: Path, port: int) -> None:
    """Le raccourci du Bureau lit ce fichier pour ouvrir le BON port (si 3214 était pris, quantbot en choisit un autre)."""
    try:
        d = Path(root) / "runtime"; d.mkdir(parents=True, exist_ok=True); (d / "terminal.port").write_text(str(port), encoding="utf-8")
    except OSError:
        pass


def serve(port: int | None = None, root: Path = ROOT, open_browser: bool = False, autosync: bool = False, workers: bool = False) -> None:
    wanted = configured_port(port)
    port = free_port(wanted)
    if port != wanted:
        print(f"Port {wanted} déjà utilisé par un autre programme : quantbot prend {port}.")
    write_port_file(root, port)
    url = f"http://{HOST}:{port}/"
    print(f"quantbot terminal : {url}  (Ctrl+C pour arrêter)")
    server = uvicorn.Server(uvicorn.Config(create_app(root), host=HOST, port=port, log_level="warning"))
    if autosync:
        _start_autosync(root)
    sup = _start_workers(root) if workers else None
    if open_browser:
        def _open() -> None:
            for _ in range(100):
                if server.started:
                    webbrowser.open(url)
                    return
                time.sleep(0.1)
        threading.Thread(target=_open, daemon=True).start()
    try:
        server.run()
    finally:
        if sup is not None:
            sup.stop()


def _start_workers(root: Path):
    from ..supervisor import start_default
    sup = start_default(root)
    if sup is not None:
        from ..risk.ledger import LedgerMonitor
        LedgerMonitor(root).start()          # registre de portefeuille FTMO simulé + coupe-circuit global (fichier KILL, jamais levé automatiquement)
    print("Processus automatiques : simulation PAPER (MT5 + crypto) lancée et surveillée ; journaux dans runtime/logs/" if sup else "Processus automatiques non disponibles dans l'exécutable : utiliser lancer_tout.bat")
    return sup


def _start_autosync(root: Path) -> None:
    from ..data.autosync import AutoSync
    AutoSync(root).start()
    print("Synchronisation automatique des données : active (Coinbase public + MT5 si disponible), état dans data/sync_status.json")


def start_background(port: int | None = None, root: Path = ROOT, autosync: bool = False) -> tuple[int, uvicorn.Server]:
    """Démarre le serveur dans un thread (fenêtre de bureau) et attend qu'il réponde."""
    port = free_port(configured_port(port))
    write_port_file(root, port)
    server = uvicorn.Server(uvicorn.Config(create_app(root), host=HOST, port=port, log_level="warning"))
    if autosync:
        _start_autosync(root)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return port, server
        time.sleep(0.1)
    raise RuntimeError("le serveur local n'a pas démarré")
