"""Exporte TOUS les trades pris (PAPER et réels) avec leur plus haut atteint (MFE), leur plus bas (MAE) et le give-back, plus un résumé (totaux des MFE, des perdants, des trades au TP).

    python scripts/export_trades_mfe.py [--root .] [--period all|session|today]

Écrit reports/exports/trades_mfe.csv (UTF-8 avec BOM, ouvrable dans Excel), reports/exports/trades_mfe_summary.json et reports/exports/trades_mfe_summary.md. Lecture seule : aucun ordre.
La même extraction est téléchargeable depuis l'interface (onglet Live trades : « Exporter CSV (MFE) »).
"""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.ui.mfe_export import build_export, to_csv


def md(s: dict) -> str:
    f = lambda d: f"{d['n']} trades · somme R {d['sum_r']:+.2f} · somme MFE {d['sum_mfe_r']:+.2f} R" + (f" · give-back {d['giveback_r']:+.2f} R" if "giveback_r" in d else "")
    L = ["# Extraction des trades avec le plus haut atteint (MFE)", "", f"Trades clos : {s['trades_closed']} (avec barres : {s['closed_with_bars']}, sans barres : {s['closed_without_bars']}) · ouverts : {s['trades_open']}", "",
         f"- Tous les trades clos : {f(s['all_closed'])}", f"- Perdants (R <= 0) : {f(s['losers'])}", f"- Perdants qui avaient un plus haut POSITIF : {f(s['losers_with_positive_mfe'])} (part des perdants : {s['losers_with_positive_mfe']['share_of_losers'] if s['losers_with_positive_mfe']['share_of_losers'] is None else round(s['losers_with_positive_mfe']['share_of_losers'], 3)} ; dont MFE >= 0,5 R : {s['losers_with_positive_mfe']['n_mfe_ge_0_5r']} ; >= 1 R : {s['losers_with_positive_mfe']['n_mfe_ge_1r']})",
         f"- Trades au TP : {f(s['take_profit'])}", "", "| Stratégie | Trades | Somme R | Somme MFE (R) | TP | Perdants | dont MFE > 0 | MFE des perdants (R) |", "|---|---|---|---|---|---|---|---|"]
    for k, v in s["by_strategy"].items():
        L.append(f"| {k} | {v['n']} | {v['sum_r']:+.2f} | {v['sum_mfe_r']:+.2f} | {v['n_tp']} | {v['n_losers']} | {v['n_losers_positive_mfe']} | {v['sum_mfe_r_losers']:+.2f} |")
    L += ["", "MFE = plus haut atteint dans le sens du trade entre l'entrée et la sortie (barres réelles), en R (R = |entrée - stop|). L'ordre des événements dans une barre est inconnu : la MFE est une borne haute pour la barre de sortie.", "Lire avec la comparaison aux entrées aléatoires : un perdant qui a d'abord gagné est banal ; seul le give-back systématique, mesuré hors échantillon, justifierait de changer une sortie."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--period", default="all", choices=["all", "session", "today"]); a = ap.parse_args(argv)
    root = Path(a.root); res = build_export(root, a.period); out = root / "reports" / "exports"; out.mkdir(parents=True, exist_ok=True)
    (out / "trades_mfe.csv").write_text("﻿" + to_csv(res["rows"]), encoding="utf-8"); (out / "trades_mfe_summary.json").write_text(json.dumps(res["summary"], indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "trades_mfe_summary.md").write_text(md(res["summary"]), encoding="utf-8"); print(md(res["summary"])); print(f"Écrit : {out / 'trades_mfe.csv'}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
