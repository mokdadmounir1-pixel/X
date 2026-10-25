"""Boucle du bot en direct : flux de barres -> moteur UNIQUE -> broker (observation ou démo durci).

Modes :
  OBSERVATION : paper trading sur les barres réelles ; AUCUN ordre n'est jamais envoyé au terminal.
  DEMO_ACTIF  : ordres envoyés par HardenedMT5Broker ; exige une approbation humaine valide ET un coupe-circuit inactif au démarrage.
Aucune exception ne peut tuer la boucle sans être journalisée et sans déclencher le coupe-circuit.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from ..config import Settings
from ..core.sim import TradingEngine
from ..exceptions import PatternBotError
from ..execution.broker import PaperBroker
from ..logging_utils import get_logger
from .approvals import check_approval
from .feed import BarFeed
from .killswitch import KillSwitch
from .mt5_exec import HardenedMT5Broker
from .state import StateStore
from .strategies import HISTORY_BARS, build_engine, load_spec, strategy_settings

log = get_logger("live.runner")


class LiveRunner:
    def __init__(self, mt5: Any, symbol: str, strategy_id: str, spec_path: str | Path, approvals_path: str | Path = "approved_strategies.json",
                 state_path: str | Path = "live_state.db", kill_file: str | Path = "KILL", timeframe: str = "M15",
                 allowed_servers: tuple = (), clock=time.time, sleep=time.sleep, feed: Any = None, force_observation: bool = False) -> None:
        """`feed` : source de barres alternative (ex. Coinbase) ; `force_observation` : simulation PAPER garantie, sans jamais lire d'approbation ni construire de broker d'ordres."""
        self.mt5, self.symbol, self.strategy_id = mt5, symbol, strategy_id
        self.force_observation = force_observation
        self.spec_path, self.approvals_path = Path(spec_path), Path(approvals_path)
        self.state = StateStore(state_path)
        self.kill = KillSwitch(self.state, kill_file)
        self.feed = feed if feed is not None else BarFeed(mt5, symbol, timeframe, HISTORY_BARS, clock=clock)
        self.allowed_servers, self.clock, self.sleep = allowed_servers, clock, sleep
        self.engine: Optional[TradingEngine] = None
        self.mode = "NON_DEMARRE"
        self.steps = 0

    # --- démarrage --------------------------------------------------------------------------
    def setup(self) -> str:
        spec = load_spec(self.spec_path)
        df = self.feed._fetch()  # historique de démarrage (barres clôturées) pour régler coûts/levier
        point = getattr(self.feed, "point", None)
        if point is None:
            point = float(getattr(self.mt5.symbol_info(self.symbol), "point", 0.0))
        df["spread"] = df["spread_points"] * float(point)
        settings: Settings = strategy_settings(spec, self.strategy_id, self.symbol, df)
        sig = build_engine(spec, self.strategy_id, settings)
        if self.force_observation:
            approved, why = False, "simulation PAPER forcée (aucune approbation lue, aucun ordre possible)"
        else:
            approved, why = check_approval(self.strategy_id, self.symbol, self.spec_path, self.approvals_path)
        blocked = self.kill.reasons()
        if approved and not blocked:
            self.mode = "DEMO_ACTIF"
            broker = HardenedMT5Broker(settings.execution, settings.ftmo, self.mt5, self.state, self.kill, self.strategy_id, self.allowed_servers)
        else:
            self.mode = "OBSERVATION"
            why = why if not approved else f"coupe-circuit actif au démarrage : {blocked}"
            self.state.set("source", getattr(self.feed, "source", "MT5"))
            broker = PaperBroker(settings.backtest.initial_equity, settings.execution)
        self.engine = TradingEngine(settings, broker=broker, signal_engine=sig, on_close=self._on_close)
        if self.mode == "DEMO_ACTIF":
            try:
                broker.restore(self.engine._n)
            except PatternBotError as exc:
                self.mode = "OBSERVATION"
                self.state.log("CRITICAL", "restore_echec", str(exc))
                self.engine.broker = PaperBroker(settings.backtest.initial_equity, settings.execution)
                why = f"reprise impossible : {exc}"
        self.state.set("mode", self.mode); self.state.set("why", why); self.state.set("strategy", self.strategy_id); self.state.set("symbol", self.symbol)
        self.state.log("INFO", "demarrage", f"mode={self.mode} ; {why}")
        return self.mode

    def _on_close(self, trade, ts) -> None:
        snap = getattr(self, "_pos_snap", None)
        snap = snap if snap and snap.get("side") == trade.side else {}
        self.state.log("INFO", "trade", json.dumps({
            "side": trade.side, "reason": trade.reason, "pnl": round(trade.pnl, 2), "r": round(trade.r_nominal, 3), "t": str(ts),
            "entry": trade.entry, "exit": trade.exit, "entry_time": str(trade.entry_time), "exit_time": str(trade.exit_time),
            "stop": snap.get("stop"), "tp": snap.get("tp"), "paper": self.mode == "OBSERVATION"}))

    def _publish(self, df=None) -> None:
        """Rend visible (page « En direct », lecture seule) ce que le bot voit et fait : barres clôturées, position, ordre en attente."""
        eng = self.engine
        if df is not None:
            tail = df.tail(240)
            self.state.set("bars", [[str(t), float(o), float(h), float(l), float(c)] for t, o, h, l, c in
                                    zip(tail.index, tail["open"], tail["high"], tail["low"], tail["close"])])
        pos = eng.broker.position
        self._pos_snap = None if pos is None else {"side": pos.side, "entry": float(pos.entry), "stop": float(pos.stop),
                                                    "tp": float(pos.take_profit), "entry_time": str(pos.entry_time), "size": float(pos.size)}
        self.state.set("position", self._pos_snap)
        dec = eng.last_decision
        self.state.set("risk", None if dec is None else {"halt": dec.halt_new, "multiplier": dec.risk_multiplier, "reasons": dec.reasons, "daily_pnl_pct": dec.daily_pnl_pct, "drawdown_pct": dec.drawdown_pct, "vol_ratio": dec.vol_ratio, "kelly_f": dec.kelly_f})
        pend = eng.pending
        self.state.set("pending", None if pend is None else {"side": pend.side, "entry": float(pend.entry), "stop": float(pend.stop),
                                                              "tp": float(pend.take_profit)})

    # --- une itération ------------------------------------------------------------------------
    def step(self) -> str:
        assert self.engine is not None, "setup() d'abord"
        self.steps += 1
        self.state.set("heartbeat", self.clock())
        try:
            df = self.feed.poll()
            if self.feed.status.hole:
                self.state.log("WARNING", "trou_de_donnees", str(self.feed.status.hole))
            if self.feed.status.stale:
                self.state.log("WARNING", "flux_fige", f"aucune nouvelle barre depuis > {self.feed.stale_after_s:.0f}s")
            if df is None:
                return "idle"
            for ts in self.feed.new_bars(df):
                self.engine.on_bar(df.loc[:ts])
                self._publish()
            self._publish(df)
            self.state.set("last_bar", str(df.index[-1]))
            return "bar"
        except PatternBotError as exc:
            self.state.log("ERROR", "erreur_cycle", str(exc))
            return "error"
        except Exception as exc:  # jamais silencieux : journal + coupe-circuit
            self.state.log("CRITICAL", "exception_inattendue", f"{type(exc).__name__}: {exc}")
            self.kill.trigger(f"exception inattendue : {type(exc).__name__}")
            return "crash"

    def run_forever(self, poll_s: float = 5.0, max_steps: Optional[int] = None) -> None:
        try:
            while max_steps is None or self.steps < max_steps:
                self.step()
                self.sleep(poll_s)
        except KeyboardInterrupt:
            self.state.log("INFO", "arret", "demandé par l'utilisateur")
