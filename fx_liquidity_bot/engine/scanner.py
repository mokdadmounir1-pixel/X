from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..instruments import PIP_SIZE, pnl_usd
from .pair_engine import PairSignalEngine, SetupCandidate, prepare_dataframe
from .risk_manager import RiskManager


@dataclass
class OpenTrade:
    pair: str
    direction: str
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    tp_source: str
    units: float
    score: float
    rr: float
    regime: str
    session: str


@dataclass
class ClosedTrade(OpenTrade):
    exit_time: pd.Timestamp = None
    exit_price: float = None
    reason: str = None
    pnl_usd: float = None


class PortfolioScanner:
    """Drives every pair's PairSignalEngine off a single shared chronological
    clock so risk limits (daily cap, concurrent trades, drawdown halt) apply
    across the whole portfolio, not per pair. When several pairs emit a
    setup at the same timestamp, the highest-scoring ones are taken first,
    up to whatever capacity the risk manager still allows -- the bot never
    forces trades just to fill the daily quota."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.risk = RiskManager(cfg)
        self.engines = {pair: PairSignalEngine(pair, cfg) for pair in cfg.pairs}
        self.open_trades: dict[str, OpenTrade] = {}
        self.closed_trades: list[ClosedTrade] = []
        self.equity_curve: list[dict] = []
        self.journal: list[dict] = []

    def run(self, data: dict[str, pd.DataFrame]):
        prepared = {pair: prepare_dataframe(df, self.cfg) for pair, df in data.items()}
        idx_maps = {pair: {ts: i for i, ts in enumerate(df.index)} for pair, df in prepared.items()}
        all_ts = sorted(set().union(*[set(df.index) for df in prepared.values()]))

        current_day = None
        for ts in all_ts:
            day = ts.date()
            if day != current_day:
                current_day = day
                self.risk.new_day(day)

            candidates: list[SetupCandidate] = []
            for pair, df in prepared.items():
                j = idx_maps[pair].get(ts)
                if j is None:
                    continue

                if pair in self.open_trades:
                    self._check_exit(pair, df, j)

                cand = self.engines[pair].process_bar(df, j)
                if cand is not None:
                    candidates.append(cand)

            candidates.sort(key=lambda c: c.score, reverse=True)
            for cand in candidates:
                self._try_open(cand)

            self.equity_curve.append({"time": ts, "equity": self.risk.state.equity})

        return self.closed_trades

    def _check_exit(self, pair, df, j):
        row = df.iloc[j]
        trade = self.open_trades[pair]
        hit_stop = row.low <= trade.stop_price if trade.direction == "long" else row.high >= trade.stop_price
        hit_target = row.high >= trade.target_price if trade.direction == "long" else row.low <= trade.target_price
        if not (hit_stop or hit_target):
            return

        exit_price, reason = (trade.stop_price, "stop") if hit_stop else (trade.target_price, "target")
        slip = self.cfg.slippage_pips * PIP_SIZE[pair]
        exit_price = exit_price - slip if trade.direction == "long" else exit_price + slip

        pnl = pnl_usd(pair, trade.entry_price, exit_price, trade.direction, trade.units)
        pnl -= self._commission(trade.units)

        closed = ClosedTrade(**trade.__dict__, exit_time=row.name, exit_price=exit_price,
                              reason=reason, pnl_usd=pnl)
        self.closed_trades.append(closed)
        self.risk.register_close(pnl)
        del self.open_trades[pair]

    def _commission(self, units: float) -> float:
        lots = units / 100_000
        return self.cfg.commission_per_lot * lots

    def _try_open(self, cand: SetupCandidate):
        if cand.pair in self.open_trades:
            return
        ok, reason = self.risk.can_enter()
        if not ok:
            self.journal.append({"pair": cand.pair, "time": cand.signal_time, "stage": "risk",
                                  "status": "rejected", "reason": reason, "score": round(cand.score, 1)})
            return

        slip = self.cfg.slippage_pips * PIP_SIZE[cand.pair]
        entry = cand.entry_price + (slip if cand.direction == "long" else -slip)
        units = self.risk.position_size_units(cand.pair, entry, cand.stop_price)
        if units <= 0:
            self.journal.append({"pair": cand.pair, "time": cand.signal_time, "stage": "risk",
                                  "status": "rejected", "reason": "invalid_position_size"})
            return

        self.open_trades[cand.pair] = OpenTrade(
            pair=cand.pair, direction=cand.direction, entry_time=cand.signal_time,
            entry_price=entry, stop_price=cand.stop_price, target_price=cand.target_price,
            tp_source=cand.tp_source, units=units, score=cand.score, rr=cand.rr,
            regime=cand.regime, session=cand.session,
        )
        self.risk.register_open()
        self.journal.append({"pair": cand.pair, "time": cand.signal_time, "stage": "trade_open",
                              "status": "accepted", "reason": "", "score": round(cand.score, 1)})
