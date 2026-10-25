"""Optimisation en marche avant (walk-forward) : on choisit les paramètres sur une fenêtre d'ENTRAÎNEMENT puis on ne retient
que la performance sur la fenêtre de TEST qui suit, jamais vue pendant le choix.

Ce que cela mesure honnêtement : la valeur de la PROCÉDURE « optimiser puis trader » hors échantillon, pas celle du meilleur jeu
de paramètres d'un balayage complet (qui est biaisé par la sélection). Le balayage tout entier compte pour UN essai dans le registre
(la grille et les fenêtres sont fixées AVANT de regarder les résultats) ; la taille de la grille est consignée.

Entrée : pour chaque configuration, la liste de ses trades (entry_time, R). Les stratégies à événements sont causales et le
sizing est en risque nominal : les trades d'une configuration ne dépendent pas du découpage en fenêtres.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from . import stats as st


@dataclass
class Window:
    train_start: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    chosen: Optional[str] = None
    train_expectancy: Optional[float] = None
    train_trades: int = 0
    oos_trades: int = 0
    oos_expectancy: Optional[float] = None
    note: str = ""


@dataclass
class WalkForwardResult:
    windows: list[Window]
    oos_r: np.ndarray
    oos_times: list
    summary: dict = field(default_factory=dict)


def make_windows(t0: pd.Timestamp, t1: pd.Timestamp, train_days: int, test_days: int) -> list[tuple]:
    """Fenêtres glissantes : [train_start, test_start) puis [test_start, test_end). Aucune fenêtre ne dépasse t1."""
    out, ts = [], t0
    tr, te = pd.Timedelta(days=train_days), pd.Timedelta(days=test_days)
    while ts + tr + te <= t1:
        out.append((ts, ts + tr, ts + tr + te))
        ts = ts + te
    return out


def _slice(trades: list, a, b) -> np.ndarray:
    return np.array([r for t, r in trades if a <= t < b], dtype=float)


def walk_forward(trades_by_config: dict, t0, t1, train_days: int = 365, test_days: int = 90, min_train_trades: int = 30,
                 min_test_trades_for_stat: int = 60) -> WalkForwardResult:
    wins = []
    chosen_oos: list = []
    oos_times: list = []
    avg_oos: list[float] = []   # repère : la configuration « moyenne » (aucune sélection) sur les mêmes fenêtres de test
    for tr0, te0, te1 in make_windows(pd.Timestamp(t0), pd.Timestamp(t1), train_days, test_days):
        w = Window(tr0, te0, te1)
        scores = {}
        for name, trades in trades_by_config.items():
            x = _slice(trades, tr0, te0)
            if len(x) >= min_train_trades:
                scores[name] = (float(x.mean()), len(x))
        per_cfg_test = [_slice(trades, te0, te1).mean() for trades in trades_by_config.values() if len(_slice(trades, te0, te1))]
        if per_cfg_test:
            avg_oos.append(float(np.mean(per_cfg_test)))
        if not scores:
            w.note = "aucune configuration n'atteint le minimum de trades à l'entraînement : fenêtre sans trade"
            wins.append(w)
            continue
        best = max(scores, key=lambda k: scores[k][0])
        w.chosen, (w.train_expectancy, w.train_trades) = best, scores[best]
        pairs = [(t, r) for t, r in trades_by_config[best] if te0 <= t < te1]
        w.oos_trades = len(pairs)
        if pairs:
            w.oos_expectancy = float(np.mean([r for _, r in pairs]))
        chosen_oos += [r for _, r in pairs]
        oos_times += [t for t, _ in pairs]
        wins.append(w)
    r = np.array(chosen_oos, dtype=float)
    traded = [w for w in wins if w.chosen]
    pos_windows = [w for w in traded if w.oos_expectancy is not None and w.oos_expectancy > 0]
    summary = {
        "n_windows": len(wins), "n_windows_traded": len(traded), "n_oos_trades": int(len(r)),
        "n_configs": len(trades_by_config),
        "oos_expectancy_R": float(r.mean()) if len(r) else None,
        "oos_profit_factor": st.profit_factor(r) if len(r) else None,
        "oos_positive_window_share": (len(pos_windows) / len(traded)) if traded else None,
        "mean_train_expectancy_of_chosen": float(np.mean([w.train_expectancy for w in traded])) if traded else None,
        "unselected_average_config_oos_R": float(np.mean(avg_oos)) if avg_oos else None,
        "distinct_choices": len({w.chosen for w in traded}),
    }
    if len(r) >= min_test_trades_for_stat:
        summary["oos_sign_flip_p"] = st.sign_flip_pvalue(r)
    else:
        summary["oos_sign_flip_p"] = None
        summary["note"] = f"moins de {min_test_trades_for_stat} trades hors échantillon : aucun test de significativité"
    if summary["oos_expectancy_R"] is not None and summary["mean_train_expectancy_of_chosen"] is not None:
        summary["optimism_gap_R"] = summary["mean_train_expectancy_of_chosen"] - summary["oos_expectancy_R"]
    return WalkForwardResult(wins, r, oos_times, summary)
