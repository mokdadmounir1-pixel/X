"""Prépare data/real automatiquement : cherche sur le disque les exports dont le SHA-256 correspond à data/real/PROVENANCE.json
et les COPIE (les sources ne sont jamais modifiées ni déplacées). Un fichier au bon nom mais au mauvais contenu est refusé.

Usage : python scripts/setup_data.py [--from DOSSIER ...] [--depth 6]
Par défaut : le dossier du projet et ses parents proches, Documents, Bureau, Téléchargements.
"""
import argparse, hashlib, json, os, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROV = ROOT / "data" / "real" / "PROVENANCE.json"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def default_roots() -> list[Path]:
    home = Path.home()
    cands = [ROOT, ROOT.parent, ROOT.parent.parent, home / "Documents", home / "Desktop", home / "Bureau", home / "Downloads", home / "Téléchargements"]
    seen, out = set(), []
    for c in cands:
        if c.is_dir() and c.resolve() not in seen:
            seen.add(c.resolve()); out.append(c)
    return out


def walk(root: Path, depth: int):
    base = len(root.parts)
    for d, dirs, files in os.walk(root):
        if len(Path(d).parts) - base >= depth:
            dirs[:] = []
        dirs[:] = [x for x in dirs if x not in {".git", "node_modules", "__pycache__", "AppData", "$Recycle.Bin"}]
        for f in files:
            if f.lower().endswith(".csv"):
                yield Path(d) / f


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="roots", action="append", type=Path)
    ap.add_argument("--depth", type=int, default=6)
    args = ap.parse_args(argv)
    prov = json.loads(PROV.read_text(encoding="utf-8"))
    want = {i["sha256"]: i for i in prov["instruments"]}
    dest_dir = ROOT / "data" / "real"
    missing = dict(want)
    for i in prov["instruments"]:                        # déjà en place et correct ?
        p = dest_dir / i["file"]
        if p.is_file() and sha256(p) == i["sha256"]:
            print(f"OK        {i['file']} déjà en place"); missing.pop(i["sha256"], None)
    for root in (args.roots or default_roots()):
        if not missing:
            break
        for p in walk(root, args.depth):
            try:
                if dest_dir in p.resolve().parents or p.stat().st_size < 1000:
                    continue
                h = sha256(p)
            except OSError:
                continue
            if h in missing:
                i = missing.pop(h)
                shutil.copy2(p, dest_dir / i["file"])
                print(f"COPIÉ     {i['file']}  depuis {p}")
    for i in missing.values():
        print(f"INTROUVABLE {i['file']} (sha256 {i['sha256'][:16]}…) : ré-exportez avec le prompt d'export MT5 ; l'empreinte changera et les résultats déjà publiés ne s'y appliqueront pas")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
