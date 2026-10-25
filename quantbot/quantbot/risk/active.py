"""Contrôle ACTIF du risque : limite de perte journalière (latent inclus), freinage par drawdown, arrêt sur dérive, arrêt sur volatilité anormale, dimensionnement Kelly PLAFONNÉ.

Principe : ce module ne peut que RÉDUIRE ou ARRÊTER l'exposition. Le multiplicateur de risque est toujours dans [min_risk_multiplier, 1] : Kelly ne fait jamais PARIER PLUS que le
risque de base (un avantage non prouvé ne doit pas augmenter la taille). Un arrêt (`halt_new`) bloque les nouvelles entrées ; il ne ferme une position que pour la perte journalière
(`flatten`). Les arrêts sur drawdown / dérive durent `halt_cooldown_days` jours puis la reprise est automatique à risque réduit ; les arrêts de volatilité cessent avec elle.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..config import ActiveRiskConfig


@dataclass
class RiskDecision:
    halt_new: bool = False
    flatten: bool = False
    risk_multiplier: float = 1.0
    reasons: list[str] = field(default_factory=list)
    daily_pnl_pct: float = 0.0
    drawdown_pct: float = 0.0
    vol_ratio: Optional[float] = None
    kelly_f: Optional[float] = None


def wilson_lower(wins: int, n: int, z: float = 1.645) -> float:
    if n == 0:
        return 0.0
    p = wins / n
    d = 1 + z * z / n
    return float((p + z * z / (2 * n) - z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d)


class ActiveRiskGuard:
    def __init__(self, cfg: ActiveRiskConfig, base_risk: float = 0.005) -> None:
        self.cfg, self._base_risk = cfg, base_risk
        self.peak = 0.0
        self.day = None
        self.day_start_equity = 0.0
        self.halted_until: Optional[pd.Timestamp] = None
        self.halt_reason = ""
        self.r_hist: deque = deque(maxlen=max(cfg.drift_window, 50, cfg.kelly_min_trades))
        self.losing_streak = 0
        self._atr: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._n_atr = 0
        self._atr_pct: deque = deque(maxlen=500)
        self.last: RiskDecision = RiskDecision()

    # --- alimentation ----------------------------------------------------------------------
    def on_trade_close(self, r_nominal: float, ts: Any) -> None:
        self.r_hist.append(float(r_nominal))
        self.losing_streak = self.losing_streak + 1 if r_nominal < 0 else 0

    def _update_vol(self, h: float, l: float, c: float) -> Optional[float]:
        pc = self._prev_close if self._prev_close is not None else c
        tr = max(h - l, abs(h - pc), abs(l - pc))
        self._prev_close = c
        self._n_atr += 1
        n = 14
        self._atr = tr if self._atr is None else (self._atr * (n - 1) + tr) / n
        if self._n_atr < n or c <= 0:
            return None
        pct = self._atr / c
        ref = float(np.median(self._atr_pct)) if len(self._atr_pct) >= 100 else None
        self._atr_pct.append(pct)
        return None if ref is None or ref <= 0 else pct / ref

    # --- décision à chaque barre ---------------------------------------------------------------
    def evaluate(self, ts: Any, equity: float, bar: tuple[float, float, float], has_position: bool = False) -> RiskDecision:
        c = self.cfg
        ts = pd.Timestamp(ts)
        d = RiskDecision()
        day = ts.date()
        if day != self.day:
            self.day, self.day_start_equity = day, equity
        self.peak = max(self.peak, equity)
        d.daily_pnl_pct = (equity - self.day_start_equity) / self.day_start_equity if self.day_start_equity > 0 else 0.0
        d.drawdown_pct = (self.peak - equity) / self.peak if self.peak > 0 else 0.0
        d.vol_ratio = self._update_vol(*bar)
        mult = 1.0

        if d.daily_pnl_pct <= -c.daily_loss_halt:
            d.halt_new = True; d.reasons.append(f"perte journalière {d.daily_pnl_pct:.2%} <= -{c.daily_loss_halt:.2%}")
            d.flatten = c.daily_loss_flatten and has_position

        if self.halted_until is not None and ts < self.halted_until:
            d.halt_new = True; d.reasons.append(self.halt_reason + f" (jusqu'au {self.halted_until.date()})")
        else:
            self.halted_until = None
            if d.drawdown_pct >= c.max_drawdown_halt:
                self._arm(ts, f"drawdown {d.drawdown_pct:.2%} >= {c.max_drawdown_halt:.2%}"); d.halt_new = True; d.reasons.append(self.halt_reason)
            elif len(self.r_hist) >= c.drift_window and float(np.mean(list(self.r_hist)[-c.drift_window:])) < c.drift_min_mean_r:
                self._arm(ts, f"dérive : espérance glissante {np.mean(list(self.r_hist)[-c.drift_window:]):+.2f} R sur {c.drift_window} trades"); d.halt_new = True; d.reasons.append(self.halt_reason)
            elif self.losing_streak >= c.max_consecutive_losses:
                self._arm(ts, f"{self.losing_streak} pertes consécutives"); d.halt_new = True; d.reasons.append(self.halt_reason)
        if d.vol_ratio is not None and d.vol_ratio >= c.vol_ratio_halt:
            d.halt_new = True; d.reasons.append(f"volatilité anormale x{d.vol_ratio:.1f} la médiane")

        # dimensionnement : freinage par drawdown puis plafond Kelly (jamais > 1)
        if d.drawdown_pct > c.dd_throttle_start:
            frac = (d.drawdown_pct - c.dd_throttle_start) / max(c.max_drawdown_halt - c.dd_throttle_start, 1e-9)
            mult = min(mult, max(c.min_risk_multiplier, 1.0 - frac))
        if len(self.r_hist) >= c.kelly_min_trades:
            r = np.array(list(self.r_hist)[-max(c.kelly_min_trades, c.drift_window, 50):], dtype=float)
            wins, losses = r[r > 0], r[r < 0]
            if len(wins) and len(losses):
                b = wins.mean() / -losses.mean()
                f = wilson_lower(int((r > 0).sum()), len(r)) - (1 - wilson_lower(int((r > 0).sum()), len(r))) / b
                d.kelly_f = float(f)
                mult = min(mult, max(c.min_risk_multiplier, min(1.0, c.kelly_fraction * f / max(self._base_risk, 1e-9)))) if f > 0 else min(mult, c.min_risk_multiplier)
            elif len(losses) and not len(wins):
                mult = min(mult, c.min_risk_multiplier)
        d.risk_multiplier = float(max(c.min_risk_multiplier, min(1.0, mult)))
        self.last = d
        return d

    def _arm(self, ts: pd.Timestamp, why: str) -> None:
        self.halted_until = ts + pd.Timedelta(days=self.cfg.halt_cooldown_days)
        self.halt_reason = why
        self.peak = 0.0       # le drawdown repart de zéro après l'arrêt : sinon la reprise serait aussitôt re-bloquée
        self.losing_streak = 0
        self.r_hist.clear()   # la fenêtre de dérive repart à neuf
