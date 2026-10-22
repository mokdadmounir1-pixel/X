"""Actions du dashboard : métadonnées, import de données, agents, verrou de gain, MT5, redémarrage."""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from ..algos.library import ALGOS, BASE_ALGOS
from ..instruments import SPECS
from .jobs import JobManager, KINDS, PKG_PARENT

FILE_OK = re.compile(r"^[A-Za-z0-9_.-]{1,120}\.csv$")
MAX_UPLOAD = 400 * 1024 * 1024
LOCK_KEYS = {"day_gain_pct": (0.0, 20.0), "arm_pct": (0.0, 20.0), "giveback_frac": (0.0, 0.95)}


class Control:
    def __init__(self, runner):
        self.r = runner
        a = getattr(runner, "cli_args", None)
        self.out = str(getattr(a, "out", None) or getattr(runner, "evo_dir", None) or "results")
        self.data_dir = Path("data")
        self.jobs = JobManager(self.out)
        self.args = a

    # ------------------------------------------------------------------ infos
    def meta(self):
        from ..engine.guardian import PROFILE_DIR
        files = []
        if self.data_dir.is_dir():
            files = [{"name": f.name, "mb": round(f.stat().st_size / 1e6, 2)} for f in sorted(self.data_dir.glob("*.csv"))]
        a = vars(self.args) if self.args is not None else {}
        keep = ("instruments", "years", "seed", "data_dir", "mt5", "start", "persistence", "out", "workers", "profile",
                "port", "speed", "replay_days", "risk", "tz")
        return {"algos": [{"name": n, "hypothese": ALGOS[n].hypothesis} for n in BASE_ALGOS],
                "instruments": sorted(SPECS), "profiles": sorted(p.stem for p in PROFILE_DIR.glob("*.yaml")),
                "kinds": KINDS, "data_dir": str(self.data_dir.resolve()), "files": files, "settings": {k: a.get(k) for k in keep},
                "platform": sys.platform, "out": str(Path(self.out).resolve()),
                "profit_lock": dict(getattr(self.r.profile, "profit_lock", {}) or {}) if self.r.profile else {}}

    def mt5(self):
        from ..live.mt5_bridge import diagnose
        ok, msg = diagnose()
        return {"ok": ok, "message": msg}

    # ------------------------------------------------------------------ agents et verrou de gain
    def agent(self, name, paused):
        for ag in self.r.agents:
            if ag.name == name:
                ag.paused = bool(paused)
                ag.pause_reason = "arrêt manuel (dashboard)" if paused else ""
                if not paused:
                    ag.status = "attente"
                self.r.notifier.notify("AGENT", f"{name} {'mis en pause' if paused else 'relancé'} depuis le dashboard")
                return {"agent": name, "paused": ag.paused}
        raise KeyError("agent inconnu")

    def all_agents(self, paused):
        for ag in self.r.agents:
            self.agent(ag.name, paused)
        return {"paused": bool(paused)}

    def profit_lock(self, cfg: dict):
        out = {}
        for k, (lo, hi) in LOCK_KEYS.items():
            v = float(cfg.get(k, 0) or 0)
            if not lo <= v <= hi:
                raise ValueError(f"{k}: entre {lo} et {hi}")
            if v:
                out[k] = v
        if "giveback_frac" in out and "arm_pct" not in out:
            raise ValueError("giveback_frac demande arm_pct (seuil d'armement du gain)")
        with self.r.lock:
            self.r.profile.profit_lock = out
            for ag in self.r.agents:
                ag.profile.profit_lock = out
                ag.sim.g.p = ag.profile
                if not out:
                    ag.sim.g.blocked_gain = False
        Path(self.out).mkdir(exist_ok=True, parents=True)
        sf = Path(self.out) / "dashboard_settings.json"
        cur = json.loads(sf.read_text()) if sf.exists() else {}
        cur["profit_lock"] = out
        sf.write_text(json.dumps(cur, indent=1))
        self.r.notifier.notify("VERROU DE GAIN", ("activé " + json.dumps(out)) if out else "désactivé")
        return {"profit_lock": out}

    # ------------------------------------------------------------------ données
    def upload(self, name, stream, length):
        if not FILE_OK.match(name or ""):
            raise ValueError("nom de fichier : lettres, chiffres, _ . - et extension .csv (ex. EURUSD_M5.csv)")
        if length <= 0 or length > MAX_UPLOAD:
            raise ValueError("taille invalide (max 400 Mo)")
        self.data_dir.mkdir(exist_ok=True, parents=True)
        tmp = self.data_dir / (name + ".part")
        left = length
        with tmp.open("wb") as f:
            while left > 0:
                b = stream.read(min(1 << 20, left))
                if not b:
                    break
                f.write(b); left -= len(b)
        if left:
            tmp.unlink(missing_ok=True)
            raise ValueError("transfert interrompu")
        tmp.replace(self.data_dir / name)
        return {"saved": name, "mb": round(length / 1e6, 2), "dir": str(self.data_dir.resolve())}

    # ------------------------------------------------------------------ redémarrage avec d'autres réglages
    def restart(self, ov: dict):
        a = self.args
        if a is None:
            raise ValueError("redémarrage indisponible (processus non lancé par la CLI)")
        d = dict(vars(a))
        src = ov.get("source")
        if src == "synth":
            d.update(data_dir=None, mt5=False)
        elif src == "csv":
            dd = Path(str(ov.get("data_dir") or self.data_dir)).expanduser()
            if not dd.is_dir():
                raise ValueError("dossier de données introuvable")
            d.update(data_dir=str(dd), mt5=False)
        elif src == "mt5":
            d.update(data_dir=None, mt5=True)
        for k, cast in (("instruments", str), ("years", float), ("replay_days", int), ("speed", float), ("risk", float),
                        ("start", str), ("seed", int), ("persistence", float), ("profile", str)):
            if ov.get(k) not in (None, ""):
                d[k] = cast(ov[k])
        if not re.match(r"^[A-Za-z0-9_.,-]+$", str(d["instruments"])) or any(x not in SPECS for x in str(d["instruments"]).split(",")):
            raise ValueError("instrument inconnu")
        argv = [sys.executable, "-m", "ftmo_algo", "dashboard"]
        skip = {"cmd", "f", "start_delay"}
        for k, v in d.items():
            if k in skip or v is None or v is False or v == "":
                continue
            argv += ["--" + k.replace("_", "-")] + ([] if v is True else [str(v)])
        argv += ["--start-delay", "2.5"]

        def _go():
            time.sleep(0.6)
            kw = {}
            if sys.platform == "win32":
                kw["creationflags"] = 0x00000008 | 0x00000200
            else:
                kw["start_new_session"] = True
            subprocess.Popen(argv, env={**os.environ, "PYTHONPATH": PKG_PARENT + os.pathsep + os.environ.get("PYTHONPATH", "")}, **kw)
            os._exit(0)
        threading.Thread(target=_go, daemon=True).start()
        return {"restarting": True, "argv": " ".join(argv[3:]), "note": "la page se recharge dans quelques secondes"}
