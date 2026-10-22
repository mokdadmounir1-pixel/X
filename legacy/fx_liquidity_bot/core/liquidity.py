from dataclasses import dataclass

import pandas as pd

SESSION_PRIORITY = ["london", "new_york", "tokyo", "sydney"]


def primary_session(active: set) -> str:
    for name in SESSION_PRIORITY:
        if name in active:
            return name
    return "none"


def _in_window(hour: int, win) -> bool:
    if win.start_hour_utc <= win.end_hour_utc:
        return win.start_hour_utc <= hour < win.end_hour_utc
    return hour >= win.start_hour_utc or hour < win.end_hour_utc


@dataclass
class LiquidityLevel:
    price: float
    kind: str          # swing_high/swing_low/session_high/session_low/daily_high/daily_low
    formed_idx: int
    direction: str      # "high" or "low"
    swept: bool = False


class LiquidityTracker:
    """Maintains the pool of unswept liquidity levels (swing points, closed
    session extremes, previous-day extremes) for one pair, updated bar by bar
    with no lookahead: a level only enters the pool once fully confirmed."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.pool: list[LiquidityLevel] = []
        self._session_acc: dict[str, dict] = {}
        self._current_session_names: set[str] = set()
        self._day = None
        self._day_high = None
        self._day_low = None

    def update(self, df: pd.DataFrame, j: int) -> None:
        row = df.iloc[j]
        cfg = self.cfg

        w = cfg.swing_fractal_width
        confirm_idx = j - w
        if confirm_idx >= 0:
            if bool(df["is_swing_high"].iloc[confirm_idx]):
                self.pool.append(LiquidityLevel(
                    float(df["high"].iloc[confirm_idx]), "swing_high", confirm_idx, "high"))
            if bool(df["is_swing_low"].iloc[confirm_idx]):
                self.pool.append(LiquidityLevel(
                    float(df["low"].iloc[confirm_idx]), "swing_low", confirm_idx, "low"))

        hour = row.name.hour
        active = {win.name for win in cfg.session_windows if _in_window(hour, win)}
        for name in active - self._current_session_names:
            self._session_acc[name] = {"high": row.high, "low": row.low}
        for name in active:
            acc = self._session_acc[name]
            acc["high"] = max(acc["high"], row.high)
            acc["low"] = min(acc["low"], row.low)
        for name in self._current_session_names - active:
            acc = self._session_acc.pop(name)
            self.pool.append(LiquidityLevel(float(acc["high"]), "session_high", j, "high"))
            self.pool.append(LiquidityLevel(float(acc["low"]), "session_low", j, "low"))
        self._current_session_names = active

        day = row.name.date()
        if self._day is None:
            self._day, self._day_high, self._day_low = day, row.high, row.low
        elif day != self._day:
            self.pool.append(LiquidityLevel(float(self._day_high), "daily_high", j, "high"))
            self.pool.append(LiquidityLevel(float(self._day_low), "daily_low", j, "low"))
            self._day, self._day_high, self._day_low = day, row.high, row.low
        else:
            self._day_high = max(self._day_high, row.high)
            self._day_low = min(self._day_low, row.low)

        max_age = cfg.liquidity_max_age_bars
        self.pool = [lv for lv in self.pool if not lv.swept and j - lv.formed_idx <= max_age]

    def find_breaches(self, df: pd.DataFrame, j: int, pip_size: float, min_breach_pips: float):
        row = df.iloc[j]
        min_breach = min_breach_pips * pip_size

        highs = [lv for lv in self.pool if not lv.swept and lv.direction == "high"
                 and row.high > lv.price + min_breach]
        lows = [lv for lv in self.pool if not lv.swept and lv.direction == "low"
                and row.low < lv.price - min_breach]

        best_high = max(highs, key=lambda lv: lv.price) if highs else None
        best_low = min(lows, key=lambda lv: lv.price) if lows else None
        return best_high, best_low
