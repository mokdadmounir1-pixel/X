"""Apprentissage par renforcement (stratégie n°10) : Q-learning TABULAIRE avec contrainte de perte journalière de type FTMO, évalué en WALK-FORWARD hors-échantillon.

État discret (tendance EMA20-EMA50 en ATR, écart à l'EMA20 en ATR, régime de volatilité), actions {plat, long, short}, récompense = position x rendement suivant (en ATR) - coût x |changement de position| - pénalité si la perte du jour dépasse `day_loss_atr`
(position forcée à plat). Rien d'opaque : la table Q est inspectable. Honnêteté : un agent RL sur ~80 000 barres de bruit APPREND LE BRUIT ; la seule preuve recevable est la performance sur la fenêtre SUIVANTE, jamais vue.
numpy seul. Aucun ordre.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..strategies.events import atr_series

ACTIONS = (0, 1, -1)


def states(df: pd.DataFrame) -> np.ndarray:
    c = pd.Series(df["close"].to_numpy(float)); atr = atr_series(df, 14); e20, e50 = c.ewm(span=20, adjust=False).mean().to_numpy(), c.ewm(span=50, adjust=False).mean().to_numpy()
    tr = np.digitize((e20 - e50) / atr, [-1.0, -0.3, 0.3, 1.0]); dev = np.digitize((c.to_numpy() - e20) / atr, [-1.5, -0.5, 0.5, 1.5]); ratio = atr / pd.Series(atr).rolling(100).mean().to_numpy()
    vol = np.digitize(np.nan_to_num(ratio, nan=1.0), [0.8, 1.2]); return tr * 15 + dev * 3 + vol                    # 5 x 5 x 3 = 75 états


def _run(S, ret, day, Q, eps, alpha, gamma, cost, day_loss, rng, learn):
    n = len(S); pos = 0; eq = np.zeros(n); day_pnl = 0.0; cur = None; poss = np.zeros(n, int)
    for i in range(1, n - 1):
        if day[i] != cur:
            cur, day_pnl = day[i], 0.0
        a = int(rng.integers(3)) if (learn and rng.random() < eps) else int(np.argmax(Q[S[i]]))
        newpos = ACTIONS[a] if day_pnl > -day_loss else 0                                   # contrainte : perte journalière dépassée -> plat
        r = newpos * ret[i + 1] - cost * abs(newpos - pos); day_pnl += r; eq[i + 1] = r; poss[i + 1] = newpos
        if learn:
            Q[S[i], a] += alpha * (r + gamma * Q[S[i + 1]].max() - Q[S[i], a])
        pos = newpos
    return eq, poss


def walk_forward(df: pd.DataFrame, train_bars: int = 8000, test_bars: int = 2000, episodes: int = 5, alpha: float = 0.1, gamma: float = 0.9, eps: float = 0.2, cost_atr: float = 0.05, day_loss_atr: float = 3.0, seed: int = 0) -> dict:
    """Apprend sur `train_bars`, joue (politique gloutonne, Q figée) sur les `test_bars` SUIVANTS, avance. Renvoie les rendements hors-échantillon en unités d'ATR."""
    S = states(df); atr = atr_series(df, 14); c = df["close"].to_numpy(float); ret = np.r_[np.diff(c) / atr[:-1], 0.0]; ret = np.nan_to_num(ret); day = df.index.normalize(); rng = np.random.default_rng(seed)
    oos, windows = [], []
    for a in range(120, len(df) - train_bars - test_bars, test_bars):
        Q = np.zeros((75, 3)); tr = slice(a, a + train_bars); te = slice(a + train_bars, a + train_bars + test_bars)
        for _ in range(episodes):
            _run(S[tr], ret[tr], day[tr], Q, eps, alpha, gamma, cost_atr, day_loss_atr, rng, True)
        eq, pos = _run(S[te], ret[te], day[te], Q, 0.0, alpha, gamma, cost_atr, day_loss_atr, rng, False)
        oos.append(eq); windows.append({"start": str(df.index[te.start]), "sum_atr": float(eq.sum()), "time_in_market": float((pos != 0).mean())})
    r = np.concatenate(oos) if oos else np.array([])
    bh = float(np.nansum(ret[120 + train_bars: 120 + train_bars + len(r)])) if len(r) else 0.0
    return {"n_windows": len(windows), "oos_sum_atr": float(r.sum()), "oos_mean_atr_per_bar": float(r.mean()) if len(r) else 0.0, "oos_sharpe_per_bar": float(r.mean() / r.std()) if len(r) > 2 and r.std() > 0 else 0.0,
            "buy_hold_sum_atr": bh, "windows": windows}
