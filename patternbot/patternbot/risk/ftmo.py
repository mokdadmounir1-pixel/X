"""Garde-fou FTMO 2-Step : le bot s'arrête AVANT les limites du challenge.

Règles modélisées (à vérifier sur ftmo.com, elles peuvent changer) :
- perte journalière max 5 % du capital initial, référence recalculée à minuit CE(S)T,
  équity flottante comprise (on prend max(balance, equity) en début de jour : conservateur) ;
- perte totale max 10 % du capital initial (statique : equity >= 90 000 $ sur 100k) ;
- objectif de profit 10 % (Challenge) / 5 % (Vérification), minimum 4 jours de trading.
Des tampons internes (4 % / 8 % par défaut) déclenchent la clôture avant la limite dure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from ..config import FtmoConfig
from ..logging_utils import get_logger

log = get_logger("ftmo")


@dataclass
class GuardStatus:
    halt_new: bool = False  # plus de nouvelle entrée
    flatten: bool = False  # clôturer les positions ouvertes
    breached: bool = False  # limite dure FTMO atteinte : compte perdu
    target_reached: bool = False
    reasons: list[str] = field(default_factory=list)
    daily_floor: float = 0.0
    total_floor: float = 0.0
    profit_pct: float = 0.0
    trading_days: int = 0


class FtmoGuard:
    def __init__(self, cfg: FtmoConfig) -> None:
        self.cfg = cfg
        self.tz = ZoneInfo(cfg.timezone)
        self._day: Optional[date] = None
        self._day_ref = cfg.initial_balance
        self.trading_days: set[date] = set()
        self.breached = False
        self._news = [(self._utc(a), self._utc(b)) for a, b in cfg.news_blackouts]

    @staticmethod
    def _utc(ts: Any) -> pd.Timestamp:
        t = pd.Timestamp(ts)
        return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")

    def _local(self, ts: Any) -> pd.Timestamp:
        return self._utc(ts).tz_convert(self.tz)

    @property
    def target(self) -> float:
        c = self.cfg
        pct = c.profit_target_challenge if c.phase == "challenge" else c.profit_target_verification
        return c.initial_balance * (1 + pct)

    def register_trade_day(self, ts: Any) -> None:
        self.trading_days.add(self._local(ts).date())

    def in_weekend_blackout(self, ts: Any) -> bool:
        if not self.cfg.flat_before_weekend:
            return False
        local = self._local(ts)
        return local.weekday() >= 5 or (local.weekday() == 4 and local.hour >= self.cfg.weekend_cutoff_hour)

    def in_news_blackout(self, ts: Any) -> bool:
        t = self._utc(ts)
        return any(a <= t <= b for a, b in self._news)

    def update(self, ts: Any, balance: float, equity: float) -> GuardStatus:
        c = self.cfg
        local_day = self._local(ts).date()
        if local_day != self._day:
            self._day = local_day
            self._day_ref = max(balance, equity)
        hard_daily = self._day_ref - c.max_daily_loss * c.initial_balance
        hard_total = c.initial_balance * (1 - c.max_total_loss)
        soft_daily = self._day_ref - (c.max_daily_loss - c.daily_loss_buffer) * c.initial_balance
        soft_total = c.initial_balance * (1 - (c.max_total_loss - c.total_loss_buffer))
        st = GuardStatus(daily_floor=soft_daily, total_floor=soft_total,
                         profit_pct=(balance / c.initial_balance - 1) * 100,
                         trading_days=len(self.trading_days))

        if equity <= hard_daily or equity <= hard_total:
            self.breached = True
            log.critical("LIMITE FTMO ATTEINTE (equity=%.2f, plancher jour=%.2f, plancher total=%.2f)",
                         equity, hard_daily, hard_total)
        if self.breached:
            st.breached = st.halt_new = st.flatten = True
            st.reasons.append("limite_ftmo_atteinte")
            return st
        if equity <= soft_daily:
            st.halt_new = st.flatten = True
            st.reasons.append("tampon_perte_journaliere")
        if equity <= soft_total:
            st.halt_new = st.flatten = True
            st.reasons.append("tampon_perte_totale")
        if self.in_weekend_blackout(ts):
            st.halt_new = st.flatten = True
            st.reasons.append("weekend")
        if self.in_news_blackout(ts):
            st.halt_new = True
            st.reasons.append("news")
        if balance >= self.target and len(self.trading_days) >= c.min_trading_days:
            st.target_reached = True
            if c.stop_after_target:
                st.halt_new = True
                st.reasons.append("objectif_atteint")
        return st

    def allowed_risk(self, equity: float, status: GuardStatus) -> float:
        """Perte maximale acceptable sur le prochain trade (SL touché)."""
        headroom = equity - max(status.daily_floor, status.total_floor)
        cap = self.cfg.max_risk_per_trade * self.cfg.initial_balance
        return max(0.0, min(cap, 0.9 * headroom))
