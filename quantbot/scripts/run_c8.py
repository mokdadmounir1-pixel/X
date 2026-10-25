"""C8 en UNE commande, sans assistant : export profond MT5 (lecture seule), contrôle d'identité avec data/real, backtests en arrière, dossier de livraison.

    python scripts/run_c8.py --terminal "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

Étapes : (1) export profond M15+H1 de XAUUSD/EURUSD/USTEC dans data/deep ; (2) barres communes avec data/real IDENTIQUES (sinon ARRÊT avant tout backtest) ;
(3) run_backward.py puis run_battery_backward.py, UNE fois ; (4) livraison-C8-<date>/ avec journaux, rapports, registre, RESULTAT.json et manifest SHA-256.
Aucun ordre, aucune lecture de la période verrouillée, aucune modification de spec. Les essais sont comptés au registre (reports/registry.jsonl).
"""
import argparse, hashlib, importlib.util, json, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.lab.registry import TrialRegistry

SYMBOLS = ["XAUUSD", "EURUSD", "USTEC"]
OHLC = ["open", "high", "low", "close"]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def overlap_diff(deep_csv: Path, real_csv: Path) -> dict:
    """Barres communes (même time_broker_epoch) : combien diffèrent, combien de la référence manquent dans le profond, combien d'antérieures s'ajoutent."""
    d, r = pd.read_csv(deep_csv), pd.read_csv(real_csv)
    m = r.merge(d, on="time_broker_epoch", suffixes=("_r", "_d"))
    diff = int(sum((m[f"{c}_r"] != m[f"{c}_d"]).sum() for c in OHLC))
    diff_rows = int(((m[[f"{c}_r" for c in OHLC]].to_numpy() != m[[f"{c}_d" for c in OHLC]].to_numpy()).any(axis=1)).sum())
    return {"common": int(len(m)), "reference_rows": int(len(r)), "reference_missing_in_deep": int(len(r) - len(m)), "rows_different": diff_rows,
            "cells_different": diff, "earlier_bars_added": int((d["time_broker_epoch"] < r["time_broker_epoch"].min()).sum()), "deep_rows": int(len(d))}


def build_manifest(folder: Path) -> list[dict]:
    out = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.name != "manifest-sha256.json":
            out.append({"file": str(p.relative_to(folder)).replace("\\", "/"), "bytes": p.stat().st_size, "sha256": sha256(p)})
    return out


def run(cmd, log: Path) -> int:
    with log.open("w", encoding="utf-8") as fh:
        return subprocess.run(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT).returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--terminal", default=None); ap.add_argument("--symbols", nargs="+", default=SYMBOLS)
    ap.add_argument("--skip-export", action="store_true", help="réutiliser data/deep déjà exporté")
    args = ap.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M"); out = ROOT / f"livraison-C8-{stamp}"; out.mkdir(parents=True)
    reg_path = ROOT / "reports" / "registry.jsonl"; before = TrialRegistry(reg_path).n_trials() if reg_path.exists() else 0
    facts = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "orders_sent": 0, "trials_before": before, "steps": {}, "overlap": {}, "coverage": {}}
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    facts["git_head"] = git.stdout.strip() or "indisponible"
    (ROOT / "data" / "deep").mkdir(parents=True, exist_ok=True)
    if not args.skip_export:
        for s in args.symbols:
            cmd = [sys.executable, "scripts/export_mt5_deep.py", "--symbol", s, "--timeframes", "M15", "H1", "--out", "data/deep"] + (["--terminal", args.terminal] if args.terminal else [])
            facts["steps"][f"export_{s}"] = run(cmd, out / f"export_{s}.log")
            prov = ROOT / "data" / "deep" / f"EXPORT-PROVENANCE-DEEP-{s}.json"
            if prov.exists():
                shutil.copy2(prov, out / prov.name)
    stop = None
    for s in args.symbols:
        deep, real = ROOT / "data" / "deep" / f"{s}_M15.csv", ROOT / "data" / "real" / f"{s}_M15.csv"
        for tf in ("M15", "H1"):
            p = ROOT / "data" / "deep" / f"{s}_{tf}.csv"
            if p.exists():
                df = pd.read_csv(p, usecols=["time_broker_epoch"]); facts["coverage"][f"{s}_{tf}"] = {
                    "bars": int(len(df)), "first_epoch": int(df.time_broker_epoch.iloc[0]), "last_epoch": int(df.time_broker_epoch.iloc[-1]),
                    "epoch_duplicates": int(df.time_broker_epoch.duplicated().sum()), "sha256": sha256(p)}
        if not (deep.exists() and real.exists()):
            stop = f"{s} : fichier M15 profond ou de référence absent"; break
        facts["overlap"][s] = ov = overlap_diff(deep, real)
        if ov["rows_different"] or ov["reference_missing_in_deep"]:
            stop = f"{s} : barres communes différentes ({ov['rows_different']}) ou manquantes ({ov['reference_missing_in_deep']}) : ARRÊT, aucun backtest lancé"; break
    facts["stopped"] = stop
    if stop is None:
        marker = ROOT / "reports" / ".c8_done"
        if marker.exists():
            facts["stopped"] = "backtests déjà lancés (reports/.c8_done) : non relancés"
        else:
            facts["steps"]["run_backward"] = run([sys.executable, "scripts/run_backward.py", "specs/backward_v1.json"], out / "backward_v1.log")
            facts["steps"]["run_battery_backward"] = run([sys.executable, "scripts/run_battery_backward.py", "specs/battery_backward_v1.json"], out / "battery_backward_v1.log")
            marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    for d in ("backward_v1", "battery_backward_v1"):
        if (ROOT / "reports" / d).is_dir():
            shutil.copytree(ROOT / "reports" / d, out / "reports" / d, dirs_exist_ok=True)
    if reg_path.exists():
        shutil.copy2(reg_path, out / "registry.jsonl")
        facts["trials_after"] = TrialRegistry(reg_path).n_trials(); facts["registry_chain_ok"] = TrialRegistry(reg_path).verify()
    facts["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    facts["note"] = "Faits seulement : aucun verdict. Lire backward_v1.log et battery_backward_v1.log ; envoyer ce dossier à Claude (registry.jsonl inclus)."
    (out / "RESULTAT.json").write_text(json.dumps(facts, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "manifest-sha256.json").write_text(json.dumps(build_manifest(out), indent=1), encoding="utf-8")
    print(json.dumps({"livraison": str(out), "stopped": facts["stopped"], "steps": facts["steps"], "trials": [before, facts.get("trials_after")]}, ensure_ascii=False))
    return 0 if not facts["stopped"] and all(v == 0 for v in facts["steps"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
