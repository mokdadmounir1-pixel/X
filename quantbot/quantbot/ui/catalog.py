"""Catalogue de TOUTES les stratégies de quantbot : ce qui existe, son résultat de recherche (verdict préenregistré), si la simulation PAPER la fait tourner et combien de trades elle a pris.

Une seule page répond à « où est telle stratégie, qu'a-t-elle donné, tourne-t-elle ? ». Les modules sans stratégie exécutable (données manquantes) y figurent aussi, avec la raison exacte.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..gui.book import build_book
from ..strategies.build import strategy_code
from .replay import list_strategies

FAMILIES = [("amd", "Session / manipulation"), ("vwap", "Réversion VWAP"), ("orb", "Ouverture (ORB)"), ("fvg", "Fair Value Gap"), ("smc", "SMC order block"), ("gq_", "Scalping or"),
            ("apex_pullback", "Repli APEX"), ("apex_levels", "Repli APEX x niveaux"), ("stop_hunt", "Stop-hunt"), ("mtf", "Multi-temporel descendant"), ("il_svr", "Indices (IL-SVR)"), ("cta", "Suivi de tendance")]


def _family(sid: str) -> str:
    for k, v in FAMILIES:
        if sid.startswith(k):
            return v
    return "Autre"


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


NOT_EXECUTABLE = [
    ("ml_lgbm", "ML LightGBM walk-forward (scripts/run_ml.py)", "ml_v1b", "Exécuté : voir reports/ml_v1b. Script de recherche (3 essais), pas rejouable dans le banc d'essai."),
    ("pairs_kalman", "Stat-arb de paires BTC/ETH (Kalman + Engle-Granger)", None, "Écrite et préenregistrée (pairs_v1), NON exécutée : données Coinbase à récupérer (le terminal les synchronise sur ton PC)."),
    ("alpha_miner", "Extraction rétrospective d'alpha (alpha_miner_v1)", "alpha_miner_v1", "Exécutée : RIEN d'exploitable. Outil d'analyse, pas une stratégie."),
    ("portfolio", "Portefeuille de toutes les stratégies (portfolio_v1)", "portfolio_v1", "Exécuté : 2 FAIL. Outil de combinaison, pas une stratégie."),
    ("statarb_tips", "Stat-arb or / taux réels TIPS", None, "NON faite : exige les taux TIPS de la FRED (clé gratuite à fournir) ; à tester quand les données existent."),
    ("cot", "Positionnement COT (Managed Money)", None, "Collecteur fait (data/external/cot_gold.csv) ; signal à tester quand l'historique est collecté. Faible puissance statistique (hebdomadaire)."),
    ("ofi_lob", "OFI / carnet / icebergs / file d'attente", None, "NON faisable en l'état : exige le carnet d'ordres réel (tailles bid/ask). La collecte de profondeur est active si le courtier l'expose."),
    ("avellaneda", "Market making Avellaneda-Stoikov", None, "NON applicable : modèle de teneur de marché ; quantbot est preneur de liquidité."),
    ("vol_arb", "Arbitrage de volatilité implicite/réalisée", None, "NON faisable : exige les options (chaîne COMEX)."),
    ("rl", "Apprentissage par renforcement (TensorTrade)", None, "NON fait : sur-ajustement quasi certain sur ~80 000 barres ; environnement séparé non installé (oss_quant_stack)."),
    ("fixings", "Saisonnalité / fixings LBMA", None, "Non testée : effet non établi ; un essai à dépenser plus tard si tu le veux."),
]


def build_catalog(root: Path) -> dict:
    ls = list_strategies(root); book = build_book(root, "all")
    run_by_id = {}
    for r in book["runners"]:
        run_by_id.setdefault(r.get("strategy"), []).append(r)
    by_code = {a["strategy_code"]: a for a in book["by_strategy"]}
    rows = []
    for s in ls["strategies"]:
        res = []
        for inst in s["instruments"]:
            d = _read(Path(root) / "reports" / s["spec"] / f"{inst}_{s['id']}.json")
            if d and d.get("evaluation"):
                m = d["evaluation"].get("metrics", {}); res.append({"instrument": inst, "verdict": d["evaluation"].get("verdict"), "expectancy_R": m.get("expectancy_R"), "profit_factor": m.get("profit_factor"),
                                                                    "n_trades": m.get("n_trades"), "gates_failed": [g["name"] for g in d["evaluation"].get("gates", []) if not g.get("ok")]})
        code = strategy_code(s["id"]); runners = run_by_id.get(s["id"], []); tr = by_code.get(code)
        rows.append({"id": s["id"], "code": code, "label": s["label"], "family": _family(s["id"]), "instruments": s["instruments"], "spec": s["spec"], "note": s.get("note", ""), "research": res,
                     "paper": {"runners": len(runners), "running": any(r.get("running") for r in runners), "trades": (tr or {}).get("n", 0), "open": (tr or {}).get("open", 0), "pnl": (tr or {}).get("pnl", 0.0)}})
    extras = []
    for sid, label, spec, status in NOT_EXECUTABLE:
        d = _read(Path(root) / "reports" / spec / "result.json") if spec else None
        extras.append({"id": sid, "label": label, "status": status, "has_report": d is not None})
    return {"strategies": rows, "other_modules": extras, "n_strategies": len(rows), "n_paper_running": sum(1 for r in rows if r["paper"]["running"]),
            "note": "Verdicts = portes de validation préenregistrées sur la période de RECHERCHE (tranche verrouillée jamais lue). Aucune stratégie n'est validée : 0 PASS. La simulation PAPER sur prix réels est le juge du futur."}
