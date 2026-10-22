"""Registre append-only des expériences : TOUT essai est consigné (échecs compris), chaîné par hachage pour que toute
modification a posteriori soit détectable. Sert à compter honnêtement les essais (Deflated Sharpe) : le nombre de
tests n'est pas « le nombre d'algos survivants » mais tout ce qui a été tenté sur la même famille de données."""
from __future__ import annotations
import hashlib
import json
import subprocess
import time
from pathlib import Path


def _git_rev():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                              cwd=Path(__file__).resolve().parent).stdout.strip() or None
    except Exception:
        return None


def family_key(instruments, real: bool) -> str:
    return ("reel:" if real else "synth:") + ",".join(sorted(instruments))


def experiment_id(kind, family, data_hash, algos, extra="") -> str:
    blob = json.dumps([kind, family, data_hash, sorted(algos or []), extra], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


class TrialRegistry:
    def __init__(self, path):
        self.path = Path(path)

    def rows(self):
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]

    def log(self, kind: str, family: str, n_trials: int, data_hash: str = "", algos=None, params=None, outcome=None,
            note: str = "") -> dict:
        rows = self.rows()
        prev = rows[-1]["hash"] if rows else "0" * 16
        eid = experiment_id(kind, family, data_hash, algos, json.dumps(params or {}, sort_keys=True, default=str))
        rec = {"seq": len(rows) + 1, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": kind,
               "family": family, "experiment": eid, "n_trials": int(n_trials), "data_hash": data_hash,
               "algos": sorted(algos or []), "params": params or {}, "outcome": outcome or {}, "note": note,
               "code": _git_rev(), "prev": prev}
        rec["hash"] = hashlib.sha256((prev + json.dumps(rec, sort_keys=True, default=str)).encode()).hexdigest()[:16]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return rec

    def verify(self) -> tuple[bool, str]:
        prev = "0" * 16
        for r in self.rows():
            h = r.pop("hash")
            if r["prev"] != prev or hashlib.sha256((prev + json.dumps(r, sort_keys=True, default=str)).encode()).hexdigest()[:16] != h:
                return False, f"chaîne rompue à l'enregistrement {r['seq']}"
            prev = h
        return True, "chaîne intacte"

    def prior_trials(self, family: str, exclude_experiment: str | None = None) -> int:
        """Essais antérieurs sur la même famille, hors ré-exécution de la MÊME expérience (même code/données/paramètres)."""
        seen, tot = set(), 0
        for r in self.rows():
            if r["family"] != family or r["experiment"] == exclude_experiment or r["experiment"] in seen:
                continue
            seen.add(r["experiment"]); tot += r["n_trials"]
        return tot
