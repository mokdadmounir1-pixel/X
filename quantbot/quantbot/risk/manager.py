"""Gestion du risque : plan de trade, limites journalières, VaR."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..config import RiskConfig
from ..logging_utils import get_logger
from ..signals.engine import Signal

log = get_logger("risk")


@dataclass
class TradePlan:
    side: str  # long | short
    entry: float
    stop: float
    take_profit: float
    size: float
    risk_amount: float
    reward_risk: float
    confidence: float
    patterns: list[str] = field(default_factory=list)
    nominal_risk: float = 0.0  # risque VISÉ (equity x risk_per_trade) : unité stable du R, même si la taille est plafonnée


def score_multiplier(confidence: float, floor: float, min_mult: float) -> float:
    """Multiplicateur CONTINU de taille selon la force du setup (0 = désactivé -> 1). confiance <= plancher -> min_mult ; confiance = 1 -> 1."""
    if floor <= 0:
        return 1.0
    return float(min(1.0, max(min_mult, (confidence - floor) / (1.0 - floor))))


def historical_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    """VaR historique (perte positive) ; 0 si pas de données."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size == 0:
        return 0.0
    return float(max(0.0, -np.percentile(r, (1 - confidence) * 100)))


class RiskManager:
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg
        self.last_rejection: Optional[str] = None
        self._day = None
        self._day_start_equity = 0.0
        self._day_pnl = 0.0
        self._day_trades = 0

    def _roll(self, ts: Any, equity: float) -> None:
        day = pd.Timestamp(ts).date()
        if day != self._day:
            self._day, self._day_start_equity = day, equity
            self._day_pnl, self._day_trades = 0.0, 0

    def can_trade(self, ts: Any, equity: float) -> tuple[bool, str]:
        self._roll(ts, equity)
        if self._day_trades >= self.cfg.max_trades_per_day:
            return False, "max_trades_per_day"
        if self._day_pnl <= -self.cfg.max_daily_loss * self._day_start_equity:
            return False, "max_daily_loss"
        return True, ""

    def register_open(self, ts: Any, equity: float) -> None:
        self._roll(ts, equity)
        self._day_trades += 1

    def register_close(self, ts: Any, pnl: float, equity: float) -> None:
        self._roll(ts, equity)
        self._day_pnl += pnl

    def _reject(self, reason: str) -> None:
        self.last_rejection = reason
        log.info("Plan rejeté : %s", reason)
        return None

    def build_plan(self, signal: Signal, equity: float, entry: Optional[float] = None,
                   max_risk: Optional[float] = None, cost_frac: float = 0.0, spread_frac_now: Optional[float] = None) -> Optional[TradePlan]:
        self.last_rejection = None
        c = self.cfg
        if not np.isfinite(signal.atr) or signal.atr <= 0:
            return self._reject("atr_invalide")
        if equity <= 0:
            return self._reject("equity_nulle")
        if c.reward_risk < c.min_reward_risk:
            return self._reject("reward_risk_insuffisant")
        entry = float(entry if entry is not None else signal.price)
        long = signal.direction == "bullish"
        custom_stop = signal.stop_price is not None
        if custom_stop:
            dist = (entry - signal.stop_price) if long else (signal.stop_price - entry)
            if dist <= 0:
                return self._reject("stop_du_mauvais_cote")
            dist = max(dist, c.min_stop_atr * signal.atr)  # plancher : un stop trop proche est élargi, jamais accepté tel quel
        else:
            dist = c.atr_stop_mult * signal.atr
        stop = entry - dist if long else entry + dist
        if stop <= 0:
            return self._reject("stop_negatif")
        if c.max_cost_r > 0 and cost_frac * entry / dist > c.max_cost_r:
            return self._reject("cout_trop_eleve")  # le spread/commission mangerait trop du risque : pas de trade
        if c.max_spread_frac > 0 and spread_frac_now is not None and spread_frac_now > c.max_spread_frac:
            return self._reject("spread_trop_large")       # pare-feu pré-trade : spread mesuré hors tolérance
        rr = c.reward_risk
        if signal.take_profit_price is not None:
            gain = (signal.take_profit_price - entry) if long else (entry - signal.take_profit_price)
            rr = gain / dist if dist > 0 else 0.0
            if rr < c.min_reward_risk:
                return self._reject("rr_insuffisant")
        target = entry + rr * dist if long else entry - rr * dist
        size = min(equity * c.risk_per_trade * score_multiplier(signal.confidence, c.score_sizing_floor, c.score_min_mult) / dist, equity * c.max_leverage / entry)
        if max_risk is not None:  # plafond externe (ex. marge restante avant les limites FTMO)
            if max_risk <= 0:
                return self._reject("marge_de_risque_epuisee")
            size = min(size, max_risk / dist)
        if size <= 0:
            return self._reject("taille_nulle")
        return TradePlan("long" if long else "short", entry, stop, target, size, size * dist,
                         rr, signal.confidence, signal.pattern_names, equity * c.risk_per_trade)
