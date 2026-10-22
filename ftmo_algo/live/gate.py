"""Conditions du passage à un compte réel / challenge payant. AFFICHÉES, jamais appliquées automatiquement."""
from __future__ import annotations


def real_account_conditions(verdict: str, locked_exp: float | None, demo_weeks: float, demo_trades: int,
                            demo_vs_backtest_gap_R: float | None, min_trades=30, max_gap_R=0.25) -> dict:
    conds = {
        "verdict_PASS": (verdict == "PASS", verdict),
        "periode_verrouillee_positive": (locked_exp is not None and locked_exp > 0, locked_exp),
        "demo_>=_4_semaines": (demo_weeks >= 4, round(demo_weeks, 1)),
        f"demo_>=_{min_trades}_trades": (demo_trades >= min_trades, demo_trades),
        "ecart_demo_backtest_dans_la_norme": (demo_vs_backtest_gap_R is not None and abs(demo_vs_backtest_gap_R) <= max_gap_R,
                                              demo_vs_backtest_gap_R),
    }
    return {"conditions": {k: {"ok": bool(v[0]), "valeur": v[1]} for k, v in conds.items()},
            "toutes_remplies": all(v[0] for v in conds.values()),
            "action": "Décision HUMAINE uniquement : aucun passage automatique au réel n'existe dans ce code."}
