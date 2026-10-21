"""Profil de règles prop firm + gardien interne (plus strict que la règle officielle)."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml

PROFILE_DIR = Path(__file__).resolve().parent.parent / "profiles"


@dataclass
class PropProfile:
    name: str = "FTMO_2STEP_100K"
    type: str = "static"
    initial_balance: float = 100000.0
    daily_loss_pct: float = 5.0
    max_loss_pct: float = 10.0
    profit_target_pct: float = 10.0
    min_trading_days: int = 4
    max_days: int = 0
    reset_tz: str = "Europe/Prague"
    guardian: dict = field(default_factory=lambda: {"daily_frac": 0.7, "total_frac": 0.7})
    verified_on: str = ""
    verified_note: str = ""

    @classmethod
    def load(cls, name_or_path: str = "ftmo_2step") -> "PropProfile":
        p = Path(name_or_path)
        if not p.exists():
            p = PROFILE_DIR / f"{name_or_path}.yaml"
        return cls(**yaml.safe_load(p.read_text()))

    # limites en USD
    @property
    def daily_limit(self) -> float:
        return self.initial_balance * self.daily_loss_pct / 100

    @property
    def max_loss(self) -> float:
        return self.initial_balance * self.max_loss_pct / 100

    @property
    def target(self) -> float:
        return self.initial_balance * self.profit_target_pct / 100


class Guardian:
    """Suit l'équité (flottant inclus). `floor` = plancher officiel (statique ou suiveur)."""

    def __init__(self, prof: PropProfile):
        self.p = prof
        self.day = None
        self.day_ref = prof.initial_balance
        self.floor = prof.initial_balance - prof.max_loss
        self.eod_peak = prof.initial_balance
        self.blocked_day = False
        self.blocked_all = False
        self.reason = ""
        self.breach = None
        self.trading_days: set = set()

    def new_day(self, day, balance, equity):
        if self.day is not None and self.p.type == "trailing_eod":
            self.eod_peak = max(self.eod_peak, balance)
            self.floor = min(self.p.initial_balance, self.eod_peak - self.p.max_loss)
        self.day = day
        self.day_ref = max(balance, equity)
        self.blocked_day = False

    def internal_daily(self):
        return self.p.daily_limit * self.p.guardian["daily_frac"] if self.p.daily_loss_pct > 0 else float("inf")

    def internal_floor(self):
        """Plancher interne : plus strict que le plancher officiel (marge = 1 - frac de la perte max)."""
        return self.floor + self.p.max_loss * (1 - self.p.guardian["total_frac"])

    def daily_loss(self, equity):
        return self.day_ref - equity

    def check_close(self, equity):
        """Appelé à la clôture d'une barre. Retourne 'flatten_day' / 'flatten_all' / None."""
        if self.p.daily_loss_pct > 0 and self.daily_loss(equity) >= self.internal_daily():
            if not self.blocked_day:
                self.blocked_day = True; self.reason = "gardien: perte journalière interne"
                return "flatten_day"
        if equity <= self.internal_floor() and not self.blocked_all:
            self.blocked_all = True; self.reason = "gardien: perte max interne"
            return "flatten_all"
        return None

    def check_official(self, worst_equity, t):
        """Violation officielle (au pire de la barre). Fige `breach`."""
        if self.breach:
            return self.breach
        if self.p.daily_loss_pct > 0 and self.day_ref - worst_equity >= self.p.daily_limit:
            self.breach = {"type": "daily_loss", "t": t, "equity": worst_equity}
        elif worst_equity <= self.floor:
            self.breach = {"type": "max_loss", "t": t, "equity": worst_equity}
        return self.breach

    def can_open(self, equity, open_risk, new_risk) -> tuple[bool, str]:
        if self.blocked_all:
            return False, "gardien_total"
        if self.blocked_day:
            return False, "gardien_jour"
        if self.p.daily_loss_pct > 0 and self.daily_loss(equity) + open_risk + new_risk > self.internal_daily():
            return False, "reserve_risque_jour"
        if equity - open_risk - new_risk <= self.internal_floor():
            return False, "reserve_risque_total"
        return True, ""
