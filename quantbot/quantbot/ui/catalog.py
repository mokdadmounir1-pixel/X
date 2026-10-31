"""Catalogue de TOUTES les stratégies de quantbot : ce qui existe, son résultat de recherche (verdict préenregistré), si la simulation PAPER la fait tourner et combien de trades elle a pris.

Une seule page répond à « où est telle stratégie, qu'a-t-elle donné, tourne-t-elle ? ». Les modules sans stratégie exécutable (données manquantes) y figurent aussi, avec la raison exacte.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..gui.book import build_book
from ..strategies.build import strategy_code
from ..strategies.external_data import missing
from .institutional60 import institutional60
from .replay import list_strategies

FAMILIES = [("amd", "Session / manipulation"), ("vwap", "Réversion VWAP"), ("orb", "Ouverture (ORB)"), ("fvg", "Fair Value Gap"), ("smc", "SMC order block"), ("gq_", "Scalping or"),
            ("apex_pullback", "Repli APEX"), ("apex_levels", "Repli APEX x niveaux"), ("stop_hunt", "Stop-hunt"), ("mtf", "Multi-temporel descendant"), ("il_svr", "Indices (IL-SVR)"), ("cta", "Suivi de tendance"), ("omega", "OMEGA (panier de 3)"), ("overnight", "Prime overnight"), ("intraday_mom", "Momentum intrajournalier"), ("kalman", "Kalman / Ornstein-Uhlenbeck"), ("orderflow", "Flux d'ordres (proxy)"), ("fixing", "Saisonnalité fixings"), ("cot", "Positionnement COT"), ("macro", "Macro taux réels"), ("ofi_depth", "Carnet réel (OFI)")]


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
    ("attention_factors", "Attention Factors (arbitrage statistique, 500 actions US)", None, "NON faite : exige les 500 plus grosses actions américaines (anciennes incluses), facteurs et apprentissage profond (LongConv, réentraînement annuel). Formules de coût et de résidu disponibles et testées (stat/equity_formulas.py). Résultats publiés (Sharpe 2,28 net) = simulation d'auteurs, code original non vérifié, impact de marché absent."),
    ("orb_stocks_in_play", "ORB cinq minutes sur actions à volume inhabituel", None, "NON faite : exige des barres de 5 minutes d'actions américaines avec volume réel d'ouverture sur 14 séances, pour tout l'univers. Formules testées (RVOL, filtres, stop 10 % ATR, coût en R). Un stop à 10 % de l'ATR rend les frais très lourds en R ; aucun protocole hors échantillon ni glissement publié."),
    ("avellaneda", "Market making Avellaneda-Stoikov (stat/avellaneda.py)", None, "Outil de recherche testé (cotations, simulation) : borne optimiste, sans file d'attente ni sélection adverse ; quantbot est preneur de liquidité, donc non exécuté."),
    ("vol_arb", "Prime de variance implicite/réalisée (stat/vol_arb.py)", None, "Outil de recherche : calcule vol réalisée et prime sur une chaîne d'options RÉELLE ; sans chaîne COMEX, aucun signal."),
    ("tail_dependence", "Dépendance de queue (risk/tail_dependence.py)", None, "Outil de risque : mesure empirique de co-chutes ; ne trade pas."),
    ("rl", "Q-learning walk-forward (ml/rl_agent.py, scripts/run_rl.py)", "rl_v1", "Agent tabulaire minimal en walk-forward strict, 1 essai ; sur-ajustement probable, verdict dans reports/rl_v1."),
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
        rows.append({"id": s["id"], "code": code, "label": s["label"], "family": _family(s["id"]), "instruments": s["instruments"], "spec": s["spec"], "note": s.get("note", ""), "research": res, "data_missing": missing(s["id"], root),
                     "paper": {"runners": len(runners), "running": any(r.get("running") for r in runners), "trades": (tr or {}).get("n", 0), "open": (tr or {}).get("open", 0), "pnl": (tr or {}).get("pnl", 0.0)}})
    extras = []
    for sid, label, spec, status in NOT_EXECUTABLE:
        d = _read(Path(root) / "reports" / spec / "result.json") if spec else None
        extras.append({"id": sid, "label": label, "status": status, "has_report": d is not None})
    return {"strategies": rows, "institutional60": institutional60(Path(root)), "other_modules": extras, "n_strategies": len(rows), "n_paper_running": sum(1 for r in rows if r["paper"]["running"]),
            "note": "Verdicts = portes de validation préenregistrées sur la période de RECHERCHE (tranche verrouillée jamais lue). Aucune stratégie n'est validée : 0 PASS. La simulation PAPER sur prix réels est le juge du futur."}
