"""Vérifie que data/real/*.csv sont présents et identiques (SHA-256) à ceux de data/real/PROVENANCE.json. Aucune écriture."""
import hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
prov = json.loads((ROOT / "data" / "real" / "PROVENANCE.json").read_text(encoding="utf-8"))
bad = 0
for i in prov["instruments"]:
    p = ROOT / "data" / "real" / i["file"]
    if not p.is_file():
        print(f"MANQUANT  {i['file']}  -> copiez l'export MT5 dans {p.parent}"); bad += 1; continue
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    ok = h == i["sha256"]
    print(f"{'OK       ' if ok else 'DIFFÉRENT'} {i['file']}  {h[:16]}…" + ("" if ok else f"  attendu {i['sha256'][:16]}… : ce n'est PAS le fichier de la recherche"))
    bad += not ok
sys.exit(1 if bad else 0)
