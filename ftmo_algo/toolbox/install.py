"""`python -m ftmo_algo install` : venv dédié, installation outil par outil, vérification par import RÉEL,
clones de référence dans vendor/, statut honnête (ok/failed + raison). Un échec n'affecte jamais le cœur."""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path
from .registry import TOOLS, VENDOR_CLONE

ROOT = Path(__file__).resolve().parents[2]
VENV = ROOT / "toolbox_env"
VENDOR = ROOT / "vendor"
STATUS = ROOT / "results" / "toolbox_status.json"


def _run(cmd, timeout=600):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)[-600:]
    except subprocess.TimeoutExpired:
        return 124, f"timeout {timeout}s"
    except Exception as e:  # noqa: BLE001
        return 1, repr(e)


def _py():
    return str(VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python"))


def verify(mod: str):
    code = f"import importlib,sys;m=importlib.import_module('{mod}');print(getattr(m,'__version__','?'))"
    rc, out = _run([_py(), "-I", "-c", code], 180)
    return rc == 0, out.strip().splitlines()[-1] if out.strip() else ""


def install_all(only: list[str] | None = None, timeout=600, clone=True, log=print):
    VENV.parent.mkdir(exist_ok=True)
    if not VENV.exists():
        rc, out = _run([sys.executable, "-m", "venv", str(VENV)], 300)
        if rc != 0:
            log("venv impossible:", out); return {}
    _run([_py(), "-m", "pip", "install", "-q", "--upgrade", "pip", "wheel", "setuptools"], 300)
    status = {}
    for pip_name, mod, repo, role in TOOLS:
        if only and pip_name not in only:
            continue
        t = time.time()
        rc, out = _run([_py(), "-m", "pip", "install", "-q", "--no-cache-dir", pip_name], timeout)
        attempts = ["pip install"]
        if rc != 0:     # tentatives de correction : roue binaire seule, puis sans dépendances optionnelles
            rc, out2 = _run([_py(), "-m", "pip", "install", "-q", "--no-cache-dir", "--only-binary=:all:", pip_name], timeout)
            attempts.append("--only-binary")
            if rc != 0:
                rc, out3 = _run([_py(), "-m", "pip", "install", "-q", "--no-cache-dir", "--no-deps", pip_name], timeout)
                attempts.append("--no-deps"); out = out + " | " + out2 + " | " + out3
        ok, ver = verify(mod) if rc == 0 else (False, "")
        reason = "" if ok else (("import échoué: " + ver) if rc == 0 else "installation échouée: " + out.replace("\n", " ")[-260:])
        if pip_name == "MetaTrader5" and not ok and sys.platform != "win32":
            reason = "paquet disponible uniquement sous Windows (terminal MT5) : à installer sur votre machine. " + reason
        status[pip_name] = {"status": "ok" if ok else "failed", "version": ver if ok else None, "module": mod,
                            "role": role, "reason": reason, "attempts": attempts, "seconds": round(time.time() - t, 1)}
        log(f"  {pip_name:22s} {status[pip_name]['status']:6s} {reason[:90]}")
    vend = {}
    if clone:
        VENDOR.mkdir(exist_ok=True)
        for repo in VENDOR_CLONE:
            dst = VENDOR / repo.split("/")[1]
            if dst.exists():
                vend[repo] = "déjà cloné"; continue
            rc, out = _run(["git", "clone", "--depth", "1", f"https://github.com/{repo}.git", str(dst)], 300)
            vend[repo] = "ok" if rc == 0 else "échec: " + out.replace("\n", " ")[-160:]
    res = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "python": sys.version.split()[0], "platform": sys.platform,
           "tools": status, "vendor": vend,
           "summary": {"ok": sum(1 for v in status.values() if v["status"] == "ok"),
                       "failed": sum(1 for v in status.values() if v["status"] != "ok"), "total": len(status)}}
    STATUS.parent.mkdir(exist_ok=True)
    STATUS.write_text(json.dumps(res, indent=1))
    return res
