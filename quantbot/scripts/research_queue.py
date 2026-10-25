"""File de recherche 24 h/24 : exécute, une fois chacune, les specs PRÉENREGISTRÉES listées dans specs/queue.json.

    python scripts/research_queue.py            # boucle continue
    python scripts/research_queue.py --once     # un passage

Règles (appliquées par le code, pas par la bonne volonté) :
- seuls des scripts de RECHERCHE de la liste blanche sont lancés (jamais la période verrouillée, jamais un ordre) ;
- une spec n'est lancée que si son fichier est COMMITÉ et non modifié (préenregistrement) ;
- chaque item ne tourne qu'une fois ; budget d'essais : si essais_actuels + essais_prévus > budget, l'item est bloqué (pas de contournement) ;
- aucune génération libre d'idées ici : de nouvelles specs sont ajoutées par un humain (ou proposées par une IA puis relues) et commitées d'abord.
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.filelock import exclusive_lock
from quantbot.lab.registry import TrialRegistry

ALLOWED = {"run_strategies", "optimize", "run_battery", "run_mtf"}


def spec_is_committed(root: Path, spec: Path) -> tuple[bool, str]:
    try:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(spec)], cwd=root, capture_output=True, text=True)
        if tracked.returncode != 0:
            return False, "spec non commitée (préenregistrement requis)"
        dirty = subprocess.run(["git", "status", "--porcelain", "--", str(spec)], cwd=root, capture_output=True, text=True).stdout.strip()
        return (False, "spec modifiée depuis le commit") if dirty else (True, "")
    except OSError as exc:
        return False, f"git indisponible : {exc}"


def run_once(root: Path, run=subprocess.run, check_git=spec_is_committed) -> dict:
    q = json.loads((root / "specs" / "queue.json").read_text(encoding="utf-8"))
    state_path = root / "reports" / "queue_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"done": {}, "blocked": {}}
    reg = TrialRegistry(root / "reports" / "registry.jsonl")
    status = {"ts": time.time(), "n_trials": reg.n_trials(), "budget": q["budget"], "ran": None, "blocked": {}, "pending": []}
    for it in q["items"]:
        if it["id"] in state["done"]:
            continue
        if it["script"] not in ALLOWED:
            status["blocked"][it["id"]] = f"script non autorisé : {it['script']}"; continue
        spec = root / it["spec"]
        ok, why = check_git(root, spec)
        if not ok:
            status["blocked"][it["id"]] = why; continue
        if reg.n_trials() + it["expected_trials"] > q["budget"]:
            status["blocked"][it["id"]] = f"budget d'essais : {reg.n_trials()} + {it['expected_trials']} > {q['budget']}"; continue
        status["pending"].append(it["id"])
        if status["ran"] is None:
            log = root / "reports" / f"queue_{it['id']}.log"
            with log.open("w", encoding="utf-8") as fh:
                rc = run([sys.executable, str(root / "scripts" / f"{it['script']}.py"), str(spec)], cwd=root, stdout=fh, stderr=subprocess.STDOUT).returncode
            state["done"][it["id"]] = {"ts": time.time(), "rc": rc, "trials_after": TrialRegistry(root / "reports" / "registry.jsonl").n_trials()}
            status["ran"] = {"id": it["id"], "rc": rc}
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    status["pending"] = [i["id"] for i in q["items"] if i["id"] not in state["done"] and i["id"] not in status["blocked"]]
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / "QUEUE_STATUS.json").write_text(json.dumps(status, indent=1), encoding="utf-8")
    return status


def main(argv=None) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("--once", action="store_true"); ap.add_argument("--poll", type=float, default=300.0)
    args = ap.parse_args(argv)
    try:
        with exclusive_lock(ROOT / "reports" / "research_queue.lock"):
            while True:
                st = run_once(ROOT)
                print(json.dumps({"ran": st["ran"], "pending": st["pending"], "blocked": list(st["blocked"]), "trials": st["n_trials"]}), flush=True)
                if args.once:
                    return 0
                time.sleep(0 if st["ran"] else args.poll)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
