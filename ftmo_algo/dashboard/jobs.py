"""Tâches lancées depuis le dashboard : liste blanche de commandes `python -m ftmo_algo ...`, paramètres validés,
jamais de shell. Chaque tâche a un journal, un code retour, et peut être arrêtée."""
from __future__ import annotations
import json
import re
import subprocess
import sys
import os
import time
from pathlib import Path

PKG_PARENT = str(Path(__file__).resolve().parents[2])      # permet `python -m ftmo_algo` depuis n'importe quel dossier

NAME = re.compile(r"^[A-Za-z0-9_.,-]{1,200}$")
KINDS = {
    "research": "recherche walk-forward + période verrouillée + 9 portes",
    "evolve": "amélioration continue des stratégies",
    "evolve-calibrate": "calibration de l'amélioration continue (scénarios nul / stable / dégradation)",
    "calibrate": "taux de faux PASS sur marchés sans edge",
    "data-check": "contrôle qualité des données",
    "target": "probabilité d'atteindre +5 %/mois (Monte Carlo)",
    "demo": "boucle démo MT5 (compte DÉMO uniquement)",
    "install": "boîte à outils open source (venv séparé)",
}
SINGLETON = {"research", "evolve", "demo", "install", "calibrate"}      # une seule instance à la fois
DATA_KINDS = {"research", "evolve", "calibrate", "data-check", "target", "demo"}


class JobError(ValueError):
    pass


def _num(p, k, lo, hi, default, cast=float):
    v = p.get(k, default)
    try:
        v = cast(v)
    except (TypeError, ValueError):
        raise JobError(f"{k}: nombre attendu")
    if not lo <= v <= hi:
        raise JobError(f"{k}: doit être entre {lo} et {hi}")
    return v


def _name(p, k, default=""):
    v = str(p.get(k, default) or "")
    if v and not NAME.match(v):
        raise JobError(f"{k}: caractères non autorisés")
    return v


def build_argv(kind: str, p: dict, out_dir: str, algos_ok: list[str], instruments_ok: set[str]) -> list[str]:
    if kind not in KINDS:
        raise JobError("commande inconnue")
    a = [sys.executable, "-m", "ftmo_algo", kind]
    if kind == "install":
        only = _name(p, "only")
        return a + (["--only", only] if only else [])
    if kind == "evolve-calibrate":
        return a + ["--n", str(_num(p, "n", 5, 200, 40, int)), "--out", out_dir]
    if kind in DATA_KINDS:
        ins = _name(p, "instruments", "US500,EURUSD,XAUUSD")
        bad = [x for x in ins.split(",") if x and x not in instruments_ok]
        if bad:
            raise JobError(f"instrument(s) inconnu(s) : {bad}")
        a += ["--instruments", ins, "--out", out_dir, "--workers", str(_num(p, "workers", 1, 32, 4, int)),
              "--seed", str(_num(p, "seed", 0, 10**6, 0, int))]
        src = p.get("source", "synth")
        if src == "csv":
            d = Path(str(p.get("data_dir", ""))).expanduser()
            if not d.is_dir():
                raise JobError("dossier de données introuvable")
            a += ["--data-dir", str(d)]
            if p.get("tz"):
                a += ["--tz", _name(p, "tz")]
        elif src == "mt5":
            a += ["--mt5", "--start", _name(p, "start", "2020-01-01")]
        else:
            a += ["--years", str(_num(p, "years", 0.5, 12, 4.0))]
            pers = _num(p, "persistence", 0.0, 1.0, 0.0)
            if pers:
                a += ["--persistence", str(pers)]
        if p.get("lock_exit"):
            a += ["--lock-exit"]
    if kind in ("research", "evolve"):
        al = [x for x in _name(p, "algos").split(",") if x]
        if any(x not in algos_ok for x in al):
            raise JobError("algo inconnu")
        if al:
            a += ["--algos", ",".join(al)]
        a += ["--tag", _name(p, "tag", "dash") or "dash"]
    if kind == "research":
        a += ["--null", str(_num(p, "null", 9, 999, 99, int))]
    if kind == "evolve":
        a += ["--shadow-months", str(_num(p, "shadow_months", 1, 6, 2, int))]
        if p.get("loop"):
            a += ["--loop", "--every-hours", str(_num(p, "every_hours", 0.1, 168, 24.0)), "--resume"]
        if p.get("locked"):
            a += ["--locked"]
    if kind == "calibrate":
        a += ["--n", str(_num(p, "n", 3, 200, 20, int)), "--null", str(_num(p, "null", 9, 999, 49, int))]
    if kind == "demo":
        a += ["--risk", str(_num(p, "risk", 0.05, 2.0, 0.5)), "--minutes", str(_num(p, "minutes", 1, 100000, 60, int))]
    if kind == "target" and p.get("all"):
        a += ["--all"]
    return a


class JobManager:
    def __init__(self, out_dir):
        self.dir = Path(out_dir) / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index = self.dir / "index.json"

    def _all(self):
        try:
            return json.loads(self.index.read_text())
        except Exception:
            return []

    def _save(self, rows):
        self.index.write_text(json.dumps(rows[-60:], ensure_ascii=False, indent=1))

    def _status(self, j):
        rc = self.dir / f"{j['id']}.rc"
        if rc.exists():
            code = int(rc.read_text() or -1)
            return ("arrêtée" if (self.dir / f"{j['id']}.stop").exists() else "terminée" if code == 0 else "échec"), code
        return "en cours", None

    def list(self):
        out = []
        for j in self._all():
            st, rc = self._status(j)
            out.append({**j, "status": st, "rc": rc})
        return out

    def running(self, kind):
        return any(j["kind"] == kind and j["status"] == "en cours" for j in self.list())

    def start(self, kind, params, out_dir, algos_ok, instruments_ok):
        argv = build_argv(kind, params, out_dir, algos_ok, instruments_ok)
        if kind in SINGLETON and self.running(kind):
            raise JobError(f"« {kind} » est déjà en cours : arrêtez-la d'abord")
        jid = time.strftime("%Y%m%d-%H%M%S") + "-" + kind
        log = self.dir / f"{jid}.log"
        log.write_bytes(("$ " + " ".join(argv[2:]) + "\n").encode())
        kw = {}
        if sys.platform == "win32":
            kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000      # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
        else:
            kw["start_new_session"] = True
        env = {**os.environ, "PYTHONPATH": PKG_PARENT + os.pathsep + os.environ.get("PYTHONPATH", "")}
        subprocess.Popen([sys.executable, "-m", "ftmo_algo.dashboard.jobwrap", str(self.dir / f"{jid}.rc"),
                          str(self.dir / f"{jid}.stop"), str(log), "--"] + argv, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, **kw)
        rows = self._all()
        rows.append({"id": jid, "kind": kind, "label": KINDS[kind], "cmd": " ".join(argv[3:]), "started": time.time()})
        self._save(rows)
        return jid

    def stop(self, jid):
        if not re.match(r"^[0-9]{8}-[0-9]{6}-[a-z-]+$", jid or ""):
            raise JobError("identifiant invalide")
        (self.dir / f"{jid}.stop").write_text("stop")

    def log_tail(self, jid, n=60):
        if not re.match(r"^[0-9]{8}-[0-9]{6}-[a-z-]+$", jid or ""):
            raise JobError("identifiant invalide")
        f = self.dir / f"{jid}.log"
        if not f.exists():
            return ""
        return "\n".join(f.read_text(errors="replace").splitlines()[-n:])
