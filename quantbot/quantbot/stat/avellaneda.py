"""Teneur de marché d'Avellaneda-Stoikov : prix de réserve et spread optimaux selon l'inventaire, puis SIMULATION de cotation sur barres (outil de recherche, pas un exécutant).

r = s - q gamma sigma^2 (T-t) ; spread = gamma sigma^2 (T-t) + (2/gamma) ln(1 + gamma/k). Cotation : bid = r - spread/2, ask = r + spread/2.
SIMULATION : un côté est « rempli » quand le plus haut (ask) ou le plus bas (bid) de la barre le touche, une unité à la fois, inventaire borné, remise à plat à la clôture de la journée. AUCUNE file d'attente, aucune
sélection adverse : les résultats sont des BORNES OPTIMISTES (un vrai teneur de marché subit les fills toxiques). quantbot est preneur de liquidité : ceci n'est pas une stratégie exécutable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def quotes(mid: float, q: float, sigma: float, t_left: float, gamma: float = 0.1, k: float = 1.5) -> dict:
    r = mid - q * gamma * sigma ** 2 * t_left; spread = gamma * sigma ** 2 * t_left + (2.0 / gamma) * np.log(1.0 + gamma / k)
    return {"reservation": float(r), "bid": float(r - spread / 2.0), "ask": float(r + spread / 2.0), "spread": float(spread)}


def simulate(df: pd.DataFrame, gamma: float = 0.1, k: float = 1.5, q_max: int = 5, sigma_window: int = 50, unit: float = 1.0, fee_per_fill: float = 0.0) -> dict:
    """PnL en unités de prix (par `unit`) d'une cotation continue sur les barres de `df` (colonnes open/high/low/close) ; remise à plat à la dernière barre de chaque jour."""
    h, l, c = (df[x].to_numpy(float) for x in ("high", "low", "close")); sig = pd.Series(np.log(c)).diff().rolling(sigma_window).std().to_numpy() * c
    day = df.index.normalize(); last_of_day = np.r_[day[1:] != day[:-1], True]; n = len(df); pos = pd.Series(np.arange(n)).groupby(day).cumcount().to_numpy(); cnt = pd.Series(np.arange(n)).groupby(day).transform('size').to_numpy(); tl = np.maximum(1.0 - pos / np.maximum(cnt, 1), 0.05); q = 0; cash = 0.0; fills = 0; inv, pnl = np.zeros(n), np.zeros(n); mtm_prev = 0.0
    for i in range(1, n):
        if not np.isfinite(sig[i - 1]) or sig[i - 1] <= 0:
            continue
        t_left = tl[i]
        qt = quotes(c[i - 1], q, sig[i - 1], t_left, gamma, k)
        if q < q_max and l[i] <= qt["bid"]:
            q += 1; cash -= qt["bid"] * unit; cash -= fee_per_fill; fills += 1
        if q > -q_max and h[i] >= qt["ask"]:
            q -= 1; cash += qt["ask"] * unit; cash -= fee_per_fill; fills += 1
        if last_of_day[i] and q != 0:
            cash += q * c[i] * unit; q = 0
        inv[i] = q; mtm = cash + q * c[i] * unit; pnl[i] = mtm - mtm_prev; mtm_prev = mtm
    return {"total_pnl": float(pnl.sum()), "fills": fills, "max_abs_inventory": int(np.abs(inv).max()), "pnl_per_fill": float(pnl.sum() / fills) if fills else 0.0,
            "daily_pnl_std": float(pd.Series(pnl, index=df.index).groupby(day).sum().std()), "note": "borne optimiste : aucune file d'attente ni sélection adverse"}
