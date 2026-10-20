"""Évaluateur FTMO 2-Step sur trajectoires d'equity (flottant inclus).

ATTENTION : les valeurs par défaut reflètent la connaissance de l'auteur du
code et n'ont PAS été revérifiées contre le site officiel au jour de
l'exécution (pas d'accès réseau ici). `FtmoRules.verified_on` reste None tant
qu'un humain ne les a pas confrontées aux règles en vigueur."""
from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pandas as pd

PRAGUE = ZoneInfo("Europe/Prague")


@dataclass(frozen=True)
class FtmoRules:
    initial_balance: float = 100_000.0
    profit_target_pct: float = 10.0       # phase 1 ; 5.0 en phase 2
    max_daily_loss_pct: float = 5.0       # de la balance initiale
    max_total_loss_pct: float = 10.0      # statique, de la balance initiale
    min_trading_days: int = 4
    # "max_balance_equity" = référence prudente (la plus haute des deux au
    # changement de jour). "start_equity" = equity de début de jour.
    daily_reference: str = "max_balance_equity"
    verified_on: str | None = None        # date de vérification humaine des règles


def prague_day(ts) -> object:
    return pd.Timestamp(ts).tz_convert(PRAGUE).date()


@dataclass
class FtmoResult:
    status: str            # passed | failed_daily_loss | failed_max_loss | incomplete
    day_index: int | None  # jours calendaires écoulés (1 = premier jour)
    trading_days: int
    worst_daily_loss_pct: float
    worst_total_loss_pct: float
    ts: object = None


def evaluate(snapshots: pd.DataFrame, trading_days: set, rules: FtmoRules) -> FtmoResult:
    """snapshots : index UTC trié, colonnes balance, equity.
    trading_days : ensemble de dates Prague où un trade a été ouvert/clos."""
    ib = rules.initial_balance
    daily_lim = rules.max_daily_loss_pct / 100 * ib
    floor = ib * (1 - rules.max_total_loss_pct / 100)
    target = ib * (1 + rules.profit_target_pct / 100)
    days = [prague_day(t) for t in snapshots.index]
    first_day = days[0] if days else None

    worst_d = worst_t = 0.0
    ref = None
    cur_day = None
    prev_bal = prev_eq = ib
    seen_trading = 0
    for ts, day, bal, eq in zip(snapshots.index, days, snapshots["balance"], snapshots["equity"]):
        if day != cur_day:
            cur_day = day
            ref = max(prev_bal, prev_eq) if rules.daily_reference == "max_balance_equity" else prev_eq
        prev_bal, prev_eq = bal, eq
        idx = (day - first_day).days + 1
        worst_d = max(worst_d, (ref - eq) / ib * 100)
        worst_t = max(worst_t, (ib - eq) / ib * 100)
        if ref - eq >= daily_lim:
            return FtmoResult("failed_daily_loss", idx, 0, worst_d, worst_t, ts)
        if eq <= floor:
            return FtmoResult("failed_max_loss", idx, 0, worst_d, worst_t, ts)
        seen_trading = len({d for d in trading_days if d <= day})
        if bal >= target and seen_trading >= rules.min_trading_days:
            return FtmoResult("passed", idx, seen_trading, worst_d, worst_t, ts)
    return FtmoResult("incomplete", None, len({d for d in trading_days}), worst_d, worst_t)
