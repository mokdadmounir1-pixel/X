"""Install + smoke-test every registry entry. Writes data/tools_status.json."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .registry import TOOLS

ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "data" / "tools_status.json"


def _run(cmd, timeout=900):
    try:
        p = subprocess.run(cmd, cwd="/tmp", capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)[-400:]
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def _check_import(mod: str):
    code, out = _run([sys.executable, "-c", f"import {mod}; print(getattr({mod}, '__version__', 'ok'))"], 120)
    return code == 0, out.strip().splitlines()[-1] if out.strip() else ""


def _one(entry, only_git: bool, only_pip: bool):
    tid, kind, target, mod, cat, why = entry
    rec = {"id": tid, "kind": kind, "category": cat, "why": why, "target": target}
    if kind == "pip":
        if only_git:
            return None
        ok, ver = _check_import(mod)
        if not ok:
            code, out = _run([sys.executable, "-m", "pip", "install", "-q", *target.split()])
            ok, ver = _check_import(mod) if code == 0 else (False, out)
        rec.update(status="ok" if ok else "failed", detail=ver)
    else:
        if only_pip:
            return None
        dest = ROOT / "vendor" / tid
        if (dest / ".git").exists():
            rec.update(status="ok", detail="already cloned")
        else:
            dest.parent.mkdir(exist_ok=True)
            code, out = _run(["git", "clone", "--depth", "1", "-q", target, str(dest)], 600)
            rec.update(status="ok" if code == 0 else "failed", detail="cloned" if code == 0 else out)
    rec["ts"] = int(time.time())
    return rec


def install_all(only_git=False, only_pip=False, workers=4):
    with ThreadPoolExecutor(workers) as ex:
        res = [r for r in ex.map(lambda e: _one(e, only_git, only_pip), TOOLS) if r]
    STATUS.parent.mkdir(exist_ok=True)
    old = {}
    if STATUS.exists():
        old = {r["id"]: r for r in json.loads(STATUS.read_text())}
    old.update({r["id"]: r for r in res})
    STATUS.write_text(json.dumps(list(old.values()), indent=1))
    return res


def load_status():
    if STATUS.exists():
        return json.loads(STATUS.read_text())
    return [{"id": t[0], "kind": t[1], "category": t[4], "why": t[5], "status": "not-installed"} for t in TOOLS]
