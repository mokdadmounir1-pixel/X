"""Trader continu (paper ou réel MT5/FTMO) qui apprend de ses trades.

Boucle par barre clôturée : garde-fou FTMO -> gestion de position -> signal -> ordre.
Chaque trade clôturé est journalisé ; tous les `improve_every` trades (à plat
uniquement) un cycle d'amélioration tourne. En réel, une version validée n'est
adoptée qu'après approbation manuelle (sauf execution.live_auto_adopt).
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import pandas as pd

from ..backtest.engine import Backtester
from ..config import Settings
from ..data.loaders import resample_ohlcv
from ..exceptions import PatternBotError
from ..execution.broker import make_broker
from ..logging_utils import get_logger
from ..memory.store import ExperimentStore
from ..risk.ftmo import FtmoGuard, GuardStatus
from ..risk.manager import RiskManager, TradePlan
from ..signals.engine import SignalEngine
from .journal import TradeJournal
from .loop import ImprovementLoop

log = get_logger("runner")


class PaperRunner:
    def __init__(self, settings: Settings, store: ExperimentStore, orchestrator=None,
                 improve_every: int = 30, history_bars: int = 1500, mt5=None) -> None:
        self.orchestrator = orchestrator
        self.store = store
        self.improve_every = improve_every
        self.history_bars = history_bars
        self.loop = ImprovementLoop(store, orchestrator=orchestrator)
        self.version, self.settings = self.loop.ensure_baseline(settings)
        self.journal = TradeJournal(store, orchestrator)
        s = self.settings
        start_equity = s.ftmo.initial_balance if s.ftmo.enabled else s.backtest.initial_equity
        self.broker = make_broker(start_equity, s.execution, ftmo=s.ftmo, mt5=mt5)
        self.guard = FtmoGuard(s.ftmo) if s.ftmo.enabled else None
        self.live = s.execution.mode == "live"
        self._build_components()
        self.pending: Optional[TradePlan] = None
        self._last_ts = None
        self._n = 0
        self._closed_since_cycle = 0
        self.promotions: list[str] = []
        self.pending_versions: list[str] = []
        self.last_status: Optional[GuardStatus] = None

    def _build_components(self) -> None:
        self.engine = SignalEngine(self.settings)
        self.risk = RiskManager(self.settings.risk)

    # --- helpers -----------------------------------------------------------
    def _record_close(self, trade, ts) -> None:
        self.risk.register_close(ts, trade.pnl, self.broker.equity())
        self.journal.record(self.version, trade)
        self._closed_since_cycle += 1

    def on_bar(self, df: pd.DataFrame) -> None:
        """Traite la dernière barre CLÔTURÉE de df (ignorée si déjà vue)."""
        ts = df.index[-1]
        if self._last_ts is not None and ts <= self._last_ts:
            return
        self._last_ts = ts
        s, bt = self.settings, self.settings.backtest
        o, h, l, c = (float(df[k].iloc[-1]) for k in ("open", "high", "low", "close"))

        # 1. ordre en attente (décidé à la clôture précédente) exécuté maintenant
        if self.pending is not None and self.broker.position is None:
            try:
                self.broker.open_position(self.pending, o, ts, self._n)
                self.risk.register_open(ts, self.broker.equity())
                if self.guard:
                    self.guard.register_trade_day(ts)
            except PatternBotError:
                log.exception("Ouverture refusée : ordre abandonné")
            self.pending = None

        # 2. sorties : serveur (réel) ou simulation barre par barre (paper)
        pos = self.broker.position
        if pos is not None:
            if self.broker.manages_exits:
                closed = self.broker.sync(ts, self._n)
                if closed is None and self._n - pos.entry_idx >= bt.max_hold_bars:
                    closed = self._safe_close(c, ts, "max_hold")
            else:
                info = Backtester._check_exit(pos, o, h, l, c, self._n - pos.entry_idx, bt.max_hold_bars)
                closed = self.broker.close_position(info[0], ts, info[1], self._n, info[2]) if info else None
            if closed is not None:
                self._record_close(closed, ts)

        # 3. garde-fou FTMO (equity flottante incluse)
        status = None
        if self.guard is not None:
            status = self.guard.update(ts, self.broker.balance(), self.broker.equity(c))
            self.last_status = status
            if status.flatten and self.broker.position is not None:
                closed = self._safe_close(c, ts, "ftmo_" + (status.reasons[0] if status.reasons else "guard"))
                if closed is not None:
                    self._record_close(closed, ts)
            if status.halt_new:
                self.pending = None

        # 4. nouveau signal
        halted = status is not None and status.halt_new
        if self.broker.position is None and self.pending is None and not halted and len(df) > bt.warmup_bars:
            ok, _ = self.risk.can_trade(ts, self.broker.equity(c))
            if ok:
                window = df.tail(bt.window_bars)
                htf = resample_ohlcv(window, s.signals.htf_rule) if s.signals.trend_filter == "htf" else None
                signal = self.engine.evaluate(window, htf)
                if self.orchestrator is not None:
                    signal = self.orchestrator.filter_signal(signal)
                if signal is not None:
                    cap = self.guard.allowed_risk(self.broker.equity(c), status) if self.guard else None
                    self.pending = self.risk.build_plan(signal, self.broker.equity(c), max_risk=cap)

        # 5. amélioration (à plat, sans ordre en attente, hors arrêt de sécurité)
        if (self._closed_since_cycle >= self.improve_every and self.broker.position is None
                and self.pending is None and not (status and status.breached)):
            self._improve(df)
        self._n += 1

    def _safe_close(self, price: float, ts, reason: str):
        try:
            return self.broker.close_position(price, ts, reason, self._n)
        except PatternBotError:
            log.exception("Clôture %s en échec : nouvelle tentative à la barre suivante", reason)
            return None

    def _improve(self, df: pd.DataFrame) -> None:
        self._closed_since_cycle = 0
        adopt = (not self.live) or self.settings.execution.live_auto_adopt
        try:
            result = self.loop.run_cycle(df.tail(self.history_bars), self.settings, auto_promote=adopt)
        except PatternBotError:
            log.exception("Cycle d'amélioration en échec : version conservée")
            return
        if result.pending_approval:
            self.pending_versions.append(result.pending_approval)
        if result.promoted:
            self.version, self.settings = self.store.current()
            self._build_components()
            self.promotions.append(self.version)
            log.info("Nouvelle version active : %s", self.version)

    def run_replay(self, df: pd.DataFrame, start: Optional[int] = None) -> None:
        for t in range(start or self.settings.backtest.warmup_bars, len(df)):
            self.on_bar(df.iloc[: t + 1])

    def run_forever(self, fetch: Callable[[], pd.DataFrame], poll_s: float = 60.0,
                    max_iterations: Optional[int] = None, sleep: Callable[[float], None] = time.sleep) -> None:
        i = 0
        try:
            while max_iterations is None or i < max_iterations:
                try:
                    self.on_bar(fetch())
                except PatternBotError as exc:
                    log.warning("Erreur de cycle, nouvelle tentative : %s", exc)
                if self.last_status is not None and self.last_status.breached:
                    log.critical("Limite FTMO atteinte : arrêt du bot")
                    break
                i += 1
                sleep(poll_s)
        except KeyboardInterrupt:
            log.info("Arrêt demandé")
