"""Moteur de trading UNIQUE : backtest, paper et démo exécutent exactement ce code.

Une seule méthode, `on_bar`, traite la dernière barre CLÔTURÉE d'une série :
ordre en attente exécuté à l'ouverture, sorties (simulées ou serveur), garde-fou,
nouveau signal -> plan de risque -> ordre en attente (exécuté à la barre suivante).
Le backtest n'est qu'un rejeu de ce code barre par barre (`run_replay`).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from ..config import Settings
from ..data.loaders import resample_ohlcv
from ..data.validation import validate_ohlcv
from ..exceptions import PatternBotError
from ..execution.broker import Broker, Trade, make_broker
from ..logging_utils import get_logger
from ..risk.ftmo import FtmoGuard, GuardStatus
from ..risk.calendar import in_weekend_blackout
from ..risk.active import ActiveRiskGuard
from ..risk.manager import RiskManager, TradePlan
from ..signals.engine import SignalEngine

log = get_logger("core.sim")


def check_exit(pos, o: float, h: float, l: float, c: float, held: int, max_hold: int):
    """Sortie d'une position sur une barre : (prix, raison, ordre_au_marché) ou None.

    Pessimiste : gap au-delà du stop -> exécution à l'ouverture ; stop ET cible dans la
    même barre -> le stop gagne ; la cible est un ordre limite (sans slippage).
    """
    if pos.side == "long":
        if o <= pos.stop:
            return float(o), "stop_gap", True
        if l <= pos.stop:
            return pos.stop, "stop_loss", True
        if h >= pos.take_profit:
            return pos.take_profit, "take_profit", False
    else:
        if o >= pos.stop:
            return float(o), "stop_gap", True
        if h >= pos.stop:
            return pos.stop, "stop_loss", True
        if l <= pos.take_profit:
            return pos.take_profit, "take_profit", False
    if held >= max_hold:
        return float(c), "max_hold", True
    return None


class TradingEngine:
    def __init__(self, settings: Settings, broker: Optional[Broker] = None, cost_multiplier: float = 1.0,
                 signal_engine: Any = None, on_close: Optional[Callable[[Trade, Any], None]] = None,
                 mt5: Any = None, overlay: Optional[Callable[[Any, Any], float]] = None) -> None:
        self.settings = settings
        self.overlay = overlay             # (ts, série de clôtures) -> multiplicateur de taille dans [0, 1] : ne peut que RÉDUIRE le risque (annonces macro, queue de pertes)
        s = settings
        start = s.ftmo.initial_balance if s.ftmo.enabled else s.backtest.initial_equity
        self.broker = broker or make_broker(start, s.execution, cost_multiplier, ftmo=s.ftmo, mt5=mt5)
        self.signals = signal_engine or SignalEngine(s)
        self.risk = RiskManager(s.risk)
        self.guard = FtmoGuard(s.ftmo) if s.ftmo.enabled else None
        self.active = ActiveRiskGuard(s.active_risk, s.risk.risk_per_trade) if s.active_risk.enabled else None
        self.last_decision = None
        self.on_close = on_close
        self.pending: Optional[TradePlan] = None
        self.last_status: Optional[GuardStatus] = None
        self.n_signals = 0
        self.rejections: dict[str, int] = {}
        self.equity_ts: list = []
        self.equity_v: list[float] = []
        self._last_ts = None
        self._n = 0
        self._seg_start = 0  # indice (dans df) du début du segment de données continu courant
        self.holes: list = []
        self.external_halt: Optional[str] = None   # raison d'un blocage venu de l'extérieur (ex. « bloc corrélé » : un autre instrument du même groupe a déjà une position) ; aucune entrée tant qu'il est posé
        self.ghosts = None                 # GhostBook facultatif : suit les signaux IGNORÉS (lecture seule, aucune influence sur les décisions)

    # --- helpers ---------------------------------------------------------
    def _reject(self, why: str) -> None:
        self.rejections[why] = self.rejections.get(why, 0) + 1

    def _ghost(self, reason: str, df: pd.DataFrame, c: float) -> None:
        """Évalue le signal courant SANS rien décider (fonction pure) et le confie au registre fantôme avec la raison de l'ignorance."""
        bt = self.settings.backtest
        try:
            window = df.iloc[self._seg_start:].tail(bt.window_bars)
            htf = resample_ohlcv(window, self.settings.signals.htf_rule) if self.settings.signals.trend_filter == "htf" else None
            signal = self.signals.evaluate(window, htf)
        except Exception:                       # jamais d'impact sur le moteur
            return
        if signal is not None:
            self._ghost_signal(signal, reason, c)

    def _ghost_signal(self, signal: Any, reason: str, c: float) -> None:
        r = self.settings.risk; long = signal.direction == "bullish"; entry = float(signal.price)
        if signal.stop_price is not None:
            dist = max((entry - signal.stop_price) if long else (signal.stop_price - entry), r.min_stop_atr * signal.atr)
        else:
            dist = r.atr_stop_mult * signal.atr
        if not (dist > 0) or dist != dist:
            return
        stop = entry - dist if long else entry + dist
        self.ghosts.add(signal.timestamp if hasattr(signal, "timestamp") else self._last_ts, "long" if long else "short", stop, signal.take_profit_price, reason, entry)

    def _closed(self, trade: Trade, ts: Any) -> None:
        self.risk.register_close(ts, trade.pnl, self.broker.equity())
        if self.active is not None:
            self.active.on_trade_close(trade.r_nominal, ts)
        if self.on_close is not None:
            self.on_close(trade, ts)

    def _safe_close(self, price: float, ts: Any, reason: str) -> Optional[Trade]:
        try:
            return self.broker.close_position(price, ts, reason, self._n)
        except PatternBotError:
            log.exception("Clôture %s en échec : nouvelle tentative à la barre suivante", reason)
            return None

    # --- une barre -------------------------------------------------------
    def on_bar(self, df: pd.DataFrame) -> None:
        """Traite la dernière barre clôturée de `df` (ignorée si déjà vue)."""
        ts = df.index[-1]
        if self._last_ts is not None and ts <= self._last_ts:
            return
        self._last_ts = ts
        s, bt = self.settings, self.settings.backtest
        o, h, l, c = (float(df[k].iloc[-1]) for k in ("open", "high", "low", "close"))
        if self.ghosts is not None:
            self.ghosts.step(ts, o, h, l, c)

        # trou de données (ex. 55 jours manquants) : jamais de position à cheval, contexte réinitialisé
        if len(df) >= 2:
            gap_h = (ts - df.index[-2]).total_seconds() / 3600.0
            if gap_h > bt.max_gap_hours:
                self.holes.append((df.index[-2], ts, round(gap_h, 1)))
                self._seg_start = len(df) - 1
                self.pending = None
                if self.broker.position is not None:
                    prev_close = float(df["close"].iloc[-2])
                    closed = self._safe_close(prev_close, df.index[-2], "data_gap")
                    if closed is not None:
                        self._closed(closed, df.index[-2])

        weekend = s.risk.flat_before_weekend and in_weekend_blackout(ts, s.risk.session_tz, s.risk.weekend_cutoff_hour)
        if weekend:
            self.pending = None  # un ordre décidé avant la coupure ne s'exécute pas en fenêtre de week-end

        if self.pending is not None and self.broker.position is None:
            try:
                self.broker.open_position(self.pending, o, ts, self._n)
                self.risk.register_open(ts, self.broker.equity())
                if self.guard:
                    self.guard.register_trade_day(ts)
            except PatternBotError:
                log.exception("Ouverture refusée : ordre abandonné")
            self.pending = None

        pos = self.broker.position
        if pos is not None:
            held = self._n - pos.entry_idx
            if self.broker.manages_exits:
                closed = self.broker.sync(ts, self._n)
                if closed is None and held >= bt.max_hold_bars:
                    closed = self._safe_close(c, ts, "max_hold")
            else:
                info = check_exit(pos, o, h, l, c, held, bt.max_hold_bars)
                closed = self.broker.close_position(info[0], ts, info[1], self._n, info[2]) if info else None
                rule = getattr(self.signals, "exit_rule", None)          # règle de sortie de la stratégie (ex. « clôture de séance supérieure à celle de la veille ») : causale, appelée sur le passé uniquement
                if closed is None and rule is not None:
                    why_exit = rule(df, pos)
                    if why_exit:
                        closed = self._safe_close(c, ts, str(why_exit))
            if closed is not None:
                self._closed(closed, ts)

        if weekend:
            if self.broker.position is not None:
                closed = self._safe_close(c, ts, "weekend")
                if closed is not None:
                    self._closed(closed, ts)

        status = None
        if self.guard is not None:
            status = self.guard.update(ts, self.broker.balance(), self.broker.equity(c))
            self.last_status = status
            if status.flatten and self.broker.position is not None:
                closed = self._safe_close(c, ts, "ftmo_" + (status.reasons[0] if status.reasons else "guard"))
                if closed is not None:
                    self._closed(closed, ts)
            if status.halt_new:
                self.pending = None

        decision = None
        if self.active is not None:   # contrôle actif : perte journalière (latent inclus), drawdown, dérive, volatilité
            decision = self.active.evaluate(ts, self.broker.equity(c), (h, l, c), self.broker.position is not None)
            if decision.flatten and self.broker.position is not None:
                closed = self._safe_close(c, ts, "active_risk_flatten")
                if closed is not None:
                    self._closed(closed, ts)
            self.last_decision = decision
            if decision.halt_new:
                self.pending = None
                self._reject("active_risk_halt")
        in_session = s.risk.session_utc_start <= ts.hour < s.risk.session_utc_end
        halted = weekend or not in_session or (status is not None and status.halt_new) or (decision is not None and decision.halt_new) or self.external_halt is not None
        in_warmup = (len(df) - self._seg_start) <= bt.warmup_bars
        if self.ghosts is not None and not in_warmup and (self.broker.position is not None or self.pending is not None or halted):
            self._ghost("position_ouverte" if (self.broker.position is not None or self.pending is not None) and not halted else
                        "week_end" if weekend else "hors_session" if not in_session else "arret_ftmo" if (status is not None and status.halt_new) else "arret_risque_actif" if (decision is not None and decision.halt_new) else (self.external_halt or "arret_externe"), df, c)
        if self.broker.position is None and self.pending is None and not halted and not in_warmup:
            ok, why = self.risk.can_trade(ts, self.broker.equity(c))
            if not ok:
                self._reject(why)
                if self.ghosts is not None:
                    self._ghost(why, df, c)
            else:
                window = df.iloc[self._seg_start:].tail(bt.window_bars)
                htf = resample_ohlcv(window, s.signals.htf_rule) if s.signals.trend_filter == "htf" else None
                signal = self.signals.evaluate(window, htf)
                if signal is not None:
                    self.n_signals += 1
                    cap = self.guard.allowed_risk(self.broker.equity(c), status) if self.guard else None
                    if decision is not None and decision.risk_multiplier < 1.0:
                        mcap = self.broker.equity(c) * s.risk.risk_per_trade * decision.risk_multiplier
                        cap = mcap if cap is None else min(cap, mcap)
                    if self.overlay is not None:
                        om = float(self.overlay(ts, df["close"].iloc[-6000:]))
                        if om < 1.0:
                            ocap = self.broker.equity(c) * s.risk.risk_per_trade * max(om, 0.0)
                            cap = ocap if cap is None else min(cap, ocap)
                    ex = s.execution
                    cost_frac = ex.spread + 2.0 * (ex.fee_rate + ex.slippage)
                    sp_now = float(df["spread"].iloc[-1]) / c if "spread" in df.columns and c > 0 else None
                    self.pending = self.risk.build_plan(signal, self.broker.equity(c), max_risk=cap, cost_frac=cost_frac, spread_frac_now=sp_now if sp_now and sp_now > 0 else None)
                    if self.pending is None:
                        self._reject(self.risk.last_rejection or "plan")
                        if self.ghosts is not None:
                            self._ghost_signal(signal, self.risk.last_rejection or "plan", c)

        self.equity_ts.append(ts)
        self.equity_v.append(self.broker.equity(c))
        self._n += 1

    def run_replay(self, df: pd.DataFrame, start: Optional[int] = None) -> None:
        for t in range(start if start is not None else self.settings.backtest.warmup_bars, len(df)):
            self.on_bar(df.iloc[: t + 1])

    def finish(self, df: pd.DataFrame) -> None:
        """Clôture une éventuelle position à la dernière clôture (fin de données)."""
        if self.broker.position is not None:
            trade = self.broker.close_position(float(df["close"].iloc[-1]), df.index[-1], "end_of_data", self._n)
            self._closed(trade, df.index[-1])
            if self.equity_v:
                self.equity_v[-1] = self.broker.equity()
