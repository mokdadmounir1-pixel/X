"""Vérifie que TOUTES les stratégies préenregistrées de la simulation PAPER sont lancées et vivantes : une ligne par (instrument, stratégie) attendu, avec son état.

    python scripts/check_all_active.py [--root .]

Attendu = les specs de supervisor.PAPER_SPECS (première spec gagnante en cas de doublon) pour le worker MT5, plus crypto_paper_v1 pour le worker Coinbase. Vivant = battement de cœur < 90 s dans runtime/paper/<instrument>_<stratégie>.db.
Les erreurs de démarrage (STATUS.json) sont affichées avec leur message. Code de sortie 0 seulement si tout est vivant. Lecture seule, aucun ordre.
"""
import argparse, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.supervisor import NOT_LAUNCHED, PAPER_SPECS


def expected(root: Path) -> list:
    out, seen = [], set()
    for sp, src in [(p, "mt5") for p in PAPER_SPECS] + [("specs/crypto_paper_v1.json", "coinbase")]:
        d = json.loads((Path(root) / sp).read_text(encoding="utf-8"))
        for name, sc in d["strategies"].items():
            for inst in sc["instruments"]:
                if (src, inst, name) not in seen:
                    seen.add((src, inst, name)); out.append({"source": src, "spec": Path(sp).stem, "instrument": inst, "strategy": name})
    return out


def state(root: Path, inst: str, name: str, now: float) -> str:
    db = Path(root) / "runtime" / "paper" / f"{inst}_{name}.db"
    if not db.is_file():
        return "ABSENT"
    from quantbot.gui.book import read_db
    d = read_db(db)
    if d is None:
        return "ILLISIBLE"
    hb = d["kv"].get("heartbeat")
    return "VIVANT" if hb is not None and now - float(hb) < 90 else ("ARRETE" if hb is not None else "SANS_BATTEMENT")


def main(argv=None) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("--root", default=str(ROOT)); a = ap.parse_args(argv); root = Path(a.root); now = time.time()
    errs = {}
    for f in sorted((root / "runtime" / "paper").glob("STATUS*.json")):
        try:
            for e in json.loads(f.read_text(encoding="utf-8")).get("errors", []):
                errs[(e["instrument"], e["strategy"])] = e["error"]
        except (OSError, ValueError):
            pass
    rows = expected(root); bad = 0
    for r in rows:
        s = state(root, r["instrument"], r["strategy"], now); r["state"] = s
        if s != "VIVANT":
            bad += 1
        print(f"{s:14s} {r['instrument']:8s} {r['strategy']:22s} ({r['spec']})" + (f"  ERREUR : {errs[(r['instrument'], r['strategy'])]}" if (r["instrument"], r["strategy"]) in errs else ""))
    print(f"\n{len(rows) - bad}/{len(rows)} lanceurs vivants.")
    if NOT_LAUNCHED:
        print("Specs volontairement non lancées par le worker MT5 :"); [print(f"  - {k} : {v}") for k, v in NOT_LAUNCHED.items()]
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
