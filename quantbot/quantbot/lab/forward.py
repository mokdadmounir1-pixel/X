"""Évaluation sur l'échantillon FUTUR (barres postérieures au gel, specs/forward_freeze.json).

Règle de non-regard : tant que la stratégie n'a pas au moins `min_trades` trades futurs, les performances sont CALCULÉES MAIS NON DIVULGUÉES
(seul le nombre de trades est rendu). Quand le seuil est atteint, la lecture est unique par stratégie et compte comme un essai (voir le script).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..backtest.engine import Backtester
from . import stats as st


def forward_trades(df_all: pd.DataFrame, settings: Any, signal_engine: Any, freeze: pd.Timestamp) -> list:
    """Trades ENTRÉS strictement après le gel. La stratégie tourne sur tout l'historique (échauffement) mais seuls les trades futurs comptent."""
    res = Backtester(settings, 1.0, signal_engine).run(df_all)
    return [t for t in res.trades if pd.Timestamp(t.entry_time) > freeze]


def evaluate_forward(trades: list, min_trades: int = 60) -> dict:
    n = len(trades)
    if n < min_trades:
        return {"n_forward_trades": n, "min_trades": min_trades, "disclosed": False,
                "note": f"{n}/{min_trades} trades futurs : performance non divulguée (règle de non-regard)"}
    r = np.array([t.r_nominal for t in trades], dtype=float)
    return {"n_forward_trades": n, "min_trades": min_trades, "disclosed": True, "expectancy_R": st.expectancy(r), "profit_factor": st.profit_factor(r),
            "worst_trade_R": float(r.min()), "win_rate": float((r > 0).mean()), "sign_flip_p": st.sign_flip_pvalue(r),
            "verdict": "CONFIRMÉ" if (st.expectancy(r) > 0 and st.profit_factor(r) > 1.0 and st.sign_flip_pvalue(r) < 0.05) else "NON CONFIRMÉ"}
