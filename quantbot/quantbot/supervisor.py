"""Superviseur des processus automatiques : lance, surveille et RELANCE les scripts (simulation PAPER MT5, simulation crypto) sans intervention.

Un processus qui s'arrête (MT5 fermé, réseau coupé, plantage) est relancé avec un délai croissant (10 s, 20 s... 300 s max) ; le délai repart de zéro si le processus a tenu 2 minutes.
Chaque processus écrit son journal dans runtime/logs/<nom>.log ; l'état (pid, relances, dernier code de sortie, dernières lignes) est dans runtime/supervisor.json (lu par l'onglet Système).
Aucun de ces scripts n'envoie d'ordre (simulation PAPER : PaperBroker uniquement). Les enfants sont arrêtés quand le terminal s'arrête.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PAPER_SPECS = ["specs/inst_strategies_v1.json", "specs/smc_v1b.json", "specs/gold_quant_v1.json", "specs/apex_pullback_v1.json", "specs/stop_hunt_v2.json", "specs/stop_hunt_v3.json", "specs/mtf_confluence_v1.json", "specs/il_svr_v1.json", "specs/cta_donchian_v1.json"]


@dataclass
class Worker:
    name: str
    argv: list[str]
    proc: Optional[subprocess.Popen] = None
    started: float = 0.0
    restarts: int = 0
    backoff: float = 10.0
    next_start: float = 0.0
    last_exit: Optional[int] = None
    state: str = "attente"
    log: Optional[Path] = None


class Supervisor:
    def __init__(self, root: Path, workers: list[tuple[str, list[str]]], base_backoff: float = 10.0, max_backoff: float = 300.0, stable_after: float = 120.0, cwd: Optional[Path] = None) -> None:
        self.root, self.cwd = Path(root), Path(cwd or root)
        self.base, self.max_b, self.stable = base_backoff, max_backoff, stable_after
        self.workers = [Worker(n, a, backoff=base_backoff) for n, a in workers]
        (self.root / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
        for w in self.workers:
            w.log = self.root / "runtime" / "logs" / f"{w.name}.log"
        self._stop = threading.Event(); self._thread: Optional[threading.Thread] = None

    def _spawn(self, w: Worker) -> None:
        fh = w.log.open("ab")
        fh.write(f"\n=== démarrage {time.strftime('%Y-%m-%d %H:%M:%S')} : {' '.join(w.argv)}\n".encode("utf-8")); fh.flush()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        w.proc = subprocess.Popen(w.argv, cwd=str(self.cwd), stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags, env=env)
        w.started, w.state = time.time(), "en cours"

    def tick(self, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        for w in self.workers:
            if w.proc is not None:
                rc = w.proc.poll()
                if rc is None:
                    if now - w.started >= self.stable:
                        w.backoff = self.base                       # a tenu : le prochain incident repart d'un délai court
                    continue
                w.last_exit, w.proc, w.state = rc, None, "arrêté"
                w.restarts += 1; w.next_start = now + w.backoff; w.backoff = min(w.backoff * 2, self.max_b)
            if w.proc is None and not self._stop.is_set() and now >= w.next_start:
                try:
                    self._spawn(w)
                except OSError as exc:
                    w.state, w.next_start = f"échec de lancement : {exc}", now + w.backoff; w.backoff = min(w.backoff * 2, self.max_b)
        self._write_status(now)

    def _tail(self, w: Worker, n: int = 6) -> list[str]:
        try:
            with w.log.open("rb") as fh:
                fh.seek(0, 2); size = fh.tell(); fh.seek(max(0, size - 4000))
                return [l for l in fh.read().decode("utf-8", "replace").splitlines() if l.strip()][-n:]
        except OSError:
            return []

    def status(self, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        return {"ts": now, "workers": [{"name": w.name, "state": w.state, "pid": w.proc.pid if w.proc else None, "restarts": w.restarts, "last_exit": w.last_exit,
                                         "uptime_s": (now - w.started) if w.proc else 0.0, "next_start_in_s": max(0.0, w.next_start - now) if w.proc is None else 0.0,
                                         "log": str(w.log), "tail": self._tail(w)} for w in self.workers]}

    def _write_status(self, now: float) -> None:
        try:
            (self.root / "runtime").mkdir(parents=True, exist_ok=True); (self.root / "runtime" / "supervisor.json").write_text(json.dumps(self.status(now), indent=1), encoding="utf-8")
        except OSError:
            pass

    def start(self, interval: float = 2.0) -> None:
        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception:                                        # le superviseur ne meurt jamais
                    pass
                self._stop.wait(interval)
        self._thread = threading.Thread(target=loop, daemon=True, name="quantbot-supervisor"); self._thread.start()

    def stop(self, grace: float = 5.0) -> None:
        self._stop.set()
        for w in self.workers:
            if w.proc is not None and w.proc.poll() is None:
                w.proc.terminate()
        deadline = time.time() + grace
        for w in self.workers:
            if w.proc is not None:
                try:
                    w.proc.wait(timeout=max(0.1, deadline - time.time()))
                except subprocess.TimeoutExpired:
                    w.proc.kill()
                w.state = "arrêté"
        self._write_status(time.time())


def default_workers(root: Path) -> list[tuple[str, list[str]]]:
    """Processus standard : simulation PAPER sur MT5 (toutes les stratégies à règles figées) et simulation crypto Coinbase (lecture seule). Aucun ordre."""
    py = sys.executable; sc = str(Path(root) / "scripts" / "paper_all.py")
    mt5 = [py, sc, "--spec", *PAPER_SPECS]
    term = os.environ.get("QUANTBOT_MT5_TERMINAL")
    if term:
        mt5 += ["--terminal", term]
    return [("paper_mt5", mt5), ("paper_coinbase", [py, sc, "--source", "coinbase"])]


def start_default(root: Path) -> Optional[Supervisor]:
    if getattr(sys, "frozen", False):          # exécutable compilé : les scripts ne sont pas embarqués -> lancer lancer_tout.bat
        return None
    sup = Supervisor(root, default_workers(root)); sup.start(); return sup
