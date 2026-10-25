# RÔLE
Tu es un ingénieur logiciel senior spécialisé en systèmes de trading automatisés, MetaTrader 5 (API Python) et sûreté d'exécution. Tu écris du code Python 3.10+ propre, testé, commenté en français, **sans dépendance superflue**. Ton code sera RELU par un autre ingénieur (Claude) avant tout usage : écris pour être audité, pas pour impressionner.

# CONTEXTE DU PROJET
Projet « quantbot » : laboratoire de recherche quantitative + exécution sur MetaTrader 5, pour un compte DÉMO (puis, un jour et seulement par décision humaine, un compte d'évaluation FTMO 2-Step 100k).
- La partie RECHERCHE est déjà écrite et testée (moteur de simulation unique, statistiques, registre d'essais, portes de validation). **Tu n'y touches pas.**
- **À ce jour AUCUNE stratégie n'a franchi les portes de validation.** Le « bot » que tu construis est donc la **plomberie d'exécution** qui tourne sur la machine Windows de l'utilisateur, à côté du terminal MT5 : flux de données, boucle de trading, envoi d'ordres durci, arrêt d'urgence, reprise après panne, surveillance. Il doit rester **inerte** (observation seule, aucun ordre) tant qu'un humain n'a pas explicitement approuvé une stratégie.
- Le moteur `TradingEngine.on_bar(df)` (code ci-dessous) est le MÊME code pour le backtest, le paper et le live : le runner ne doit pas réimplémenter la logique de trading, seulement l'alimenter.

# RÈGLES ABSOLUES (non négociables)
1. **Aucun trading réel automatique.** Tout envoi d'ordre exige : compte en mode DÉMO (`account_info().trade_mode == ACCOUNT_TRADE_MODE_DEMO`) OU double autorisation humaine explicite (config + variable d'environnement) ; liste blanche de serveurs ; `expected_login` correspondant. Par défaut : refus.
2. **Aucune stratégie ne trade sans approbation humaine.** Le runner lit un fichier `approved_strategies.json` (écrit À LA MAIN par l'utilisateur, jamais par le programme) : `{"approved": [{"id": "...", "spec_hash": "...", "approved_by": "...", "date": "..."}]}`. Fichier absent ou stratégie non listée = mode OBSERVATION (signaux journalisés, zéro ordre).
3. **Ne modifie AUCUNE logique de validation** (portes, seuils, statistiques, registre, périodes verrouillées) ni aucun fichier de spécification `specs/*.json`. Ne propose jamais d'« améliorer » un seuil pour obtenir de meilleurs résultats. N'affirme aucune performance.
4. **Pas de martingale, pas de moyennage à la baisse, pas d'augmentation de taille après perte, pas de grille, pas de levier supérieur à `risk.max_leverage`.** Le dimensionnement vient exclusivement de `RiskManager` / `FtmoGuard` existants.
5. **Chaque ordre porte son stop et sa cible au moment de l'envoi** (côté serveur). Jamais de position sans stop.
6. **Écriture avant envoi (write-ahead)** : chaque intention d'ordre est journalisée (SQLite ou JSON lines, avec un identifiant unique) AVANT l'appel à `order_send`. Une réponse ambiguë (timeout, retcode inconnu, `None`) = état « INCONNU » : suspendre toute nouvelle entrée et réconcilier avec `positions_get` / `history_deals_get` avant de continuer. Jamais de ré-envoi aveugle.
7. **`order_check` obligatoire avant `order_send`** ; refuser si `retcode` ≠ succès ou si la marge est insuffisante.
8. **Aucun secret dans le code ni dans le journal** (pas d'identifiant, mot de passe, numéro de compte complet). Ne demande jamais ces informations.
9. **Aucun accès réseau** autre que le terminal MT5 local (pas de télémétrie, pas de webhook, pas de téléchargement).
10. **Honnêteté** : si tu ne peux pas tester quelque chose (le vrai terminal MT5 n'existe pas dans ton environnement), dis-le explicitement. Tout test se fait contre un faux MT5 (voir `FakeMT5` ci-dessous). Ne prétends jamais qu'un code « a été testé sur MT5 ».

# CE QUE TU DOIS PRODUIRE (une tâche par message ; attends mon « suivant » avant d'enchaîner)
T1. `quantbot/live/feed.py` — flux de barres MT5 : lit les N dernières barres CLÔTURÉES (la barre en formation, position 0, est TOUJOURS écartée), les convertit au format du projet (`open, high, low, close, volume` ; index UTC naïf via `broker_clock_to_utc(..., "eu_dst")` de `quantbot/data/mt5.py`), n'émet une barre qu'une seule fois, détecte les trous (> `backtest.max_gap_hours`) et les flux figés (aucune nouvelle barre alors que le marché est censé être ouvert), et se reconnecte proprement.
T2. `quantbot/live/runner.py` — boucle : à chaque nouvelle barre clôturée, appelle `TradingEngine.on_bar(df)` avec un `MT5Broker` (ou un broker d'observation qui ne fait que journaliser), gère l'approbation (règle 2), le garde-fou FTMO déjà fourni, l'arrêt propre (Ctrl+C), et ne laisse jamais une exception tuer la boucle sans journal ni coupe-circuit.
T3. Durcissement de `MT5Broker` (`quantbot/execution/broker.py`) : `order_check` avant `order_send`, détection du mode de remplissage (`symbol_info().filling_mode` : FOK/IOC/RETURN) au lieu de IOC en dur, gestion des retcodes (requote, prix modifié, hors session, marge, volume invalide), retry borné avec le même identifiant d'intention (jamais de doublon), journal write-ahead (règle 6), `reconcile()` au démarrage (positions déjà ouvertes avec notre `magic`).
T4. `quantbot/live/killswitch.py` — arrêt d'urgence : fichier `KILL` présent OU perte journalière atteinte OU état INCONNU non résolu => plus aucune entrée ; option de clôture de toutes les positions portant notre `magic`. Persistant au redémarrage.
T5. `quantbot/live/state.py` — état persistant (SQLite) : intentions, ordres, positions, dernier horodatage de barre traité, compteurs ; reprise après redémarrage sans rejouer ni doubler d'ordre.
T6. Surveillance : endpoint JSON local en lecture seule (`/api/live`) à ajouter au serveur d'interface existant (127.0.0.1 UNIQUEMENT) : mode (OBSERVATION / DÉMO ACTIF), dernière barre, positions, intentions en cours, état du coupe-circuit, dernières erreurs.
T7. `scripts/run_live.py` + `docs/EXPLOITATION.md` : lancement, arrêt, reprise, que faire en cas d'état INCONNU, liste de contrôle avant d'approuver une stratégie (rappelant que l'approbation est une décision humaine).

# CRITÈRES D'ACCEPTATION (pour CHAQUE tâche)
- Tests `pytest` fournis, déterministes, SANS terminal MT5 (utilise `FakeMT5` ci-dessous, étends-le si nécessaire). Couvre au minimum : cas nominal, timeout/réponse ambiguë, retcode de refus, redémarrage au milieu d'une intention, barre répétée, flux figé, compte non démo, stratégie non approuvée, présence du fichier KILL.
- Aucun appel à `order_send` possible quand : mode observation, compte non autorisé, coupe-circuit actif, état INCONNU, stratégie non approuvée. Écris un test par cas.
- Le code ne duplique pas la logique de trading : il appelle `TradingEngine` / `RiskManager` / `FtmoGuard`.
- Réponse structurée : (1) liste des fichiers créés/modifiés, (2) code complet de chaque fichier, (3) tests, (4) ce qui N'A PAS pu être testé, (5) risques résiduels que tu vois.

# FORMAT DE LIVRAISON
Un fichier par bloc de code, avec son chemin en titre. Pas de pseudo-code. Pas de « TODO » laissé dans le chemin d'exécution des ordres. Si une exigence te paraît ambiguë ou dangereuse, POSE LA QUESTION avant d'écrire du code.

# INTERFACES EXISTANTES (code réel du projet, à utiliser tel quel)

### quantbot/core/sim.py
```python
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
                 mt5: Any = None) -> None:
        self.settings = settings
        s = settings
        start = s.ftmo.initial_balance if s.ftmo.enabled else s.backtest.initial_equity
        self.broker = broker or make_broker(start, s.execution, cost_multiplier, ftmo=s.ftmo, mt5=mt5)
        self.signals = signal_engine or SignalEngine(s)
        self.risk = RiskManager(s.risk)
        self.guard = FtmoGuard(s.ftmo) if s.ftmo.enabled else None
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

    # --- helpers ---------------------------------------------------------
    def _reject(self, why: str) -> None:
        self.rejections[why] = self.rejections.get(why, 0) + 1

    def _closed(self, trade: Trade, ts: Any) -> None:
        self.risk.register_close(ts, trade.pnl, self.broker.equity())
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

        in_session = s.risk.session_utc_start <= ts.hour < s.risk.session_utc_end
        halted = weekend or not in_session or (status is not None and status.halt_new)
        in_warmup = (len(df) - self._seg_start) <= bt.warmup_bars
        if self.broker.position is None and self.pending is None and not halted and not in_warmup:
            ok, why = self.risk.can_trade(ts, self.broker.equity(c))
            if not ok:
                self._reject(why)
            else:
                window = df.iloc[self._seg_start:].tail(bt.window_bars)
                htf = resample_ohlcv(window, s.signals.htf_rule) if s.signals.trend_filter == "htf" else None
                signal = self.signals.evaluate(window, htf)
                if signal is not None:
                    self.n_signals += 1
                    cap = self.guard.allowed_risk(self.broker.equity(c), status) if self.guard else None
                    ex = s.execution
                    cost_frac = ex.spread + 2.0 * (ex.fee_rate + ex.slippage)
                    self.pending = self.risk.build_plan(signal, self.broker.equity(c), max_risk=cap, cost_frac=cost_frac)
                    if self.pending is None:
                        self._reject(self.risk.last_rejection or "plan")

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
```
### quantbot/execution/broker.py
```python
"""Couche d'exécution : interface broker, paper trading, MetaTrader 5 réel.

Le trading réel (MT5Broker) exige un TRIPLE verrou : execution.mode="live",
execution.allow_live=true, variable d'environnement QUANTBOT_ALLOW_LIVE=1,
et ftmo.enabled=true (le garde-fou FTMO est obligatoire en réel).
MT5Broker n'a pu être validé que contre un faux module MT5 (tests) : à essayer
d'abord sur un compte d'essai FTMO / démo.
"""
from __future__ import annotations

import math
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from ..config import ExecutionConfig, FtmoConfig
from ..exceptions import ExecutionError, LiveTradingDisabledError
from ..logging_utils import get_logger
from ..risk.manager import TradePlan

log = get_logger("execution")


@dataclass
class Position:
    side: str
    entry: float
    size: float
    stop: float
    take_profit: float
    entry_time: Any
    entry_fee: float
    entry_idx: int = 0
    confidence: float = 0.0
    patterns: list[str] = field(default_factory=list)
    risk_amount: float = 0.0  # perte prévue si le stop est touché (taille plafonnée incluse)
    nominal_risk: float = 0.0  # risque visé avant plafonnement du levier

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1


@dataclass
class Trade:
    side: str
    entry_time: Any
    exit_time: Any
    entry: float
    exit: float
    size: float
    pnl: float
    reason: str
    confidence: float = 0.0
    patterns: list[str] = field(default_factory=list)
    bars_held: int = 0
    risk_amount: float = 0.0
    nominal_risk: float = 0.0

    @property
    def r_nominal(self) -> float:
        """Résultat en multiples du risque NOMINAL (equity x risk_per_trade) : borné par le levier, jamais « infini »."""
        return self.pnl / self.nominal_risk if self.nominal_risk > 0 else 0.0

    @property
    def r(self) -> float:
        """Résultat en multiples du risque initial (0 si le risque est inconnu)."""
        return self.pnl / self.risk_amount if self.risk_amount > 0 else 0.0


class Broker(ABC):
    @abstractmethod
    def open_position(self, plan: TradePlan, market_price: float, ts: Any, idx: int = 0) -> Position: ...

    @abstractmethod
    def close_position(self, price: float, ts: Any, reason: str, idx: int = 0, market: bool = True) -> Trade: ...

    @abstractmethod
    def equity(self, mark_price: Optional[float] = None) -> float: ...

    def balance(self) -> float:
        return self.equity()

    #: True si le broker gère lui-même SL/TP côté serveur (réel)
    manages_exits = False

    def sync(self, ts: Any, idx: int = 0) -> Optional[Trade]:
        """Détecte une clôture côté serveur (SL/TP) ; no-op en paper."""
        return None


class PaperBroker(Broker):
    def __init__(self, initial_equity: float, cfg: ExecutionConfig, cost_multiplier: float = 1.0) -> None:
        self.cash = float(initial_equity)
        self.fee_rate = cfg.fee_rate * cost_multiplier
        self.slippage = (cfg.slippage + cfg.spread / 2) * cost_multiplier
        self.position: Optional[Position] = None
        self.trades: list[Trade] = []

    def open_position(self, plan, market_price, ts, idx=0):
        if self.position is not None:
            raise ExecutionError("Position déjà ouverte")
        sign = 1 if plan.side == "long" else -1
        fill = market_price * (1 + sign * self.slippage)
        fee = self.fee_rate * fill * plan.size
        self.cash -= fee
        self.position = Position(plan.side, fill, plan.size, plan.stop, plan.take_profit, ts, fee, idx,
                                 plan.confidence, list(plan.patterns), plan.risk_amount, plan.nominal_risk)
        log.debug("OPEN %s %.4f @ %.4f", plan.side, plan.size, fill)
        return self.position

    def close_position(self, price, ts, reason, idx=0, market=True):
        pos = self.position
        if pos is None:
            raise ExecutionError("Aucune position à fermer")
        fill = price * (1 - pos.sign * self.slippage) if market else price  # TP = ordre limite
        gross = (fill - pos.entry) * pos.size * pos.sign
        exit_fee = self.fee_rate * fill * pos.size
        self.cash += gross - exit_fee
        trade = Trade(pos.side, pos.entry_time, ts, pos.entry, fill, pos.size,
                      gross - exit_fee - pos.entry_fee, reason, pos.confidence, pos.patterns,
                      idx - pos.entry_idx, pos.risk_amount, pos.nominal_risk)
        self.trades.append(trade)
        self.position = None
        log.debug("CLOSE %s @ %.4f (%s) pnl=%.2f", pos.side, fill, reason, trade.pnl)
        return trade

    def balance(self):
        return self.cash

    def equity(self, mark_price=None):
        pos = self.position
        if pos is None or mark_price is None:
            return self.cash
        return self.cash + (mark_price - pos.entry) * pos.size * pos.sign


class MT5Broker(Broker):
    """Ordres réels via le terminal MetaTrader 5 (compte FTMO ou démo).

    `mt5` est injectable (faux module en test). Un seul symbole, coté dans la
    devise du compte (ex. EURUSD sur compte USD) : pas de conversion de devise.
    SL/TP sont posés côté serveur à l'ouverture.
    """

    manages_exits = True

    def __init__(self, cfg: ExecutionConfig, ftmo: FtmoConfig, mt5=None) -> None:
        if cfg.mode != "live" or not cfg.allow_live or os.environ.get("QUANTBOT_ALLOW_LIVE") != "1":
            raise LiveTradingDisabledError(
                "Trading réel désactivé : execution.mode=live, execution.allow_live=true "
                "ET QUANTBOT_ALLOW_LIVE=1 requis")
        if not ftmo.enabled:
            raise LiveTradingDisabledError("Le garde-fou FTMO (ftmo.enabled) est obligatoire en réel")
        if mt5 is None:
            try:
                import MetaTrader5 as mt5  # type: ignore
            except ImportError as exc:
                raise ExecutionError("Paquet MetaTrader5 indisponible (Windows + terminal MT5 requis)") from exc
        self.mt5, self.cfg = mt5, cfg
        self.symbol = cfg.mt5_symbol
        self.position: Optional[Position] = None
        self.trades: list[Trade] = []
        self._ticket: Optional[int] = None
        if not mt5.initialize():
            raise ExecutionError(f"Initialisation MT5 impossible : {mt5.last_error()}")
        acct = mt5.account_info()
        if acct is None:
            raise ExecutionError("Compte MT5 introuvable (terminal connecté ?)")
        if ftmo.expected_login is not None and acct.login != ftmo.expected_login:
            raise ExecutionError(f"Compte MT5 {acct.login} différent du compte attendu {ftmo.expected_login}")
        info = mt5.symbol_info(self.symbol)
        if info is None or not mt5.symbol_select(self.symbol, True):
            raise ExecutionError(f"Symbole MT5 indisponible : {self.symbol}")
        if getattr(info, "currency_profit", acct.currency) != acct.currency:
            raise ExecutionError(
                f"{self.symbol} est coté en {info.currency_profit}, compte en {acct.currency} : "
                "conversion de devise non supportée")
        log.warning("MT5 RÉEL actif : compte %s (%s) symbole %s", acct.login, getattr(acct, "server", "?"), self.symbol)

    # --- état du compte
    def balance(self) -> float:
        return float(self.mt5.account_info().balance)

    def equity(self, mark_price=None) -> float:
        return float(self.mt5.account_info().equity)

    def _lots(self, units: float) -> float:
        info = self.mt5.symbol_info(self.symbol)
        step = info.volume_step or 0.01
        lots = math.floor(units / info.trade_contract_size / step + 1e-9) * step
        lots = round(min(lots, info.volume_max), 8)
        if lots < info.volume_min:
            raise ExecutionError(f"Taille {units:.0f} u. < volume minimum ({info.volume_min} lot)")
        return lots

    def _find_ticket(self) -> Optional[int]:
        for p in self.mt5.positions_get(symbol=self.symbol) or ():
            if p.magic == self.cfg.mt5_magic:
                return int(p.ticket)
        return None

    def open_position(self, plan, market_price, ts, idx=0):
        if self.position is not None:
            raise ExecutionError("Position déjà ouverte")
        mt5 = self.mt5
        lots = self._lots(plan.size)
        tick = mt5.symbol_info_tick(self.symbol)
        long = plan.side == "long"
        price = tick.ask if long else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": lots,
            "type": mt5.ORDER_TYPE_BUY if long else mt5.ORDER_TYPE_SELL, "price": price,
            "sl": float(plan.stop), "tp": float(plan.take_profit), "deviation": self.cfg.mt5_deviation_points,
            "magic": self.cfg.mt5_magic, "comment": "quantbot", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise ExecutionError(f"order_send refusé : {getattr(result, 'retcode', None)} "
                                 f"{getattr(result, 'comment', mt5.last_error())}")
        contract = mt5.symbol_info(self.symbol).trade_contract_size
        self._ticket = self._find_ticket()
        self.position = Position(plan.side, float(result.price or price), lots * contract, plan.stop,
                                 plan.take_profit, ts, 0.0, idx, plan.confidence, list(plan.patterns),
                                 plan.risk_amount, plan.nominal_risk)
        log.warning("ORDRE RÉEL %s %.2f lot @ %.5f SL=%.5f TP=%.5f", plan.side, lots, self.position.entry,
                    plan.stop, plan.take_profit)
        return self.position

    def _deals_trade(self, ts, reason, idx) -> Trade:
        pos = self.position
        deals = list(self.mt5.history_deals_get(position=self._ticket) or ()) if self._ticket else []
        pnl = sum(getattr(d, "profit", 0.0) + getattr(d, "commission", 0.0) + getattr(d, "swap", 0.0)
                  + getattr(d, "fee", 0.0) for d in deals)
        exit_price = float(deals[-1].price) if deals else pos.entry
        trade = Trade(pos.side, pos.entry_time, ts, pos.entry, exit_price, pos.size, float(pnl), reason,
                      pos.confidence, pos.patterns, idx - pos.entry_idx, pos.risk_amount, pos.nominal_risk)
        self.trades.append(trade)
        self.position, self._ticket = None, None
        return trade

    def sync(self, ts, idx=0):
        if self.position is None:
            return None
        if self._ticket is None:
            self._ticket = self._find_ticket()
        if self._ticket is not None and self._find_ticket() == self._ticket:
            return None  # toujours ouverte
        return self._deals_trade(ts, "server_exit", idx)

    def close_position(self, price, ts, reason, idx=0, market=True):
        pos = self.position
        if pos is None:
            raise ExecutionError("Aucune position à fermer")
        mt5 = self.mt5
        if self._ticket is None:
            self._ticket = self._find_ticket()
        if self._ticket is None:  # déjà clôturée côté serveur
            return self._deals_trade(ts, reason, idx)
        tick = mt5.symbol_info_tick(self.symbol)
        long = pos.side == "long"
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "position": self._ticket,
            "volume": self._lots(pos.size), "type": mt5.ORDER_TYPE_SELL if long else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if long else tick.ask, "deviation": self.cfg.mt5_deviation_points,
            "magic": self.cfg.mt5_magic, "comment": f"quantbot:{reason}"[:30],
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise ExecutionError(f"Clôture refusée : {getattr(result, 'retcode', None)} "
                                 f"{getattr(result, 'comment', mt5.last_error())}")
        log.warning("CLÔTURE RÉELLE %s (%s)", pos.side, reason)
        return self._deals_trade(ts, reason, idx)


def make_broker(initial_equity: float, cfg: ExecutionConfig, cost_multiplier: float = 1.0,
                ftmo: Optional[FtmoConfig] = None, mt5=None) -> Broker:
    if cfg.mode == "live":
        return MT5Broker(cfg, ftmo or FtmoConfig(), mt5)
    return PaperBroker(initial_equity, cfg, cost_multiplier)
```
### quantbot/risk/ftmo.py
```python
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
```
### quantbot/risk/manager.py
```python
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
                   max_risk: Optional[float] = None, cost_frac: float = 0.0) -> Optional[TradePlan]:
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
        rr = c.reward_risk
        if signal.take_profit_price is not None:
            gain = (signal.take_profit_price - entry) if long else (entry - signal.take_profit_price)
            rr = gain / dist if dist > 0 else 0.0
            if rr < c.min_reward_risk:
                return self._reject("rr_insuffisant")
        target = entry + rr * dist if long else entry - rr * dist
        size = min(equity * c.risk_per_trade / dist, equity * c.max_leverage / entry)
        if max_risk is not None:  # plafond externe (ex. marge restante avant les limites FTMO)
            if max_risk <= 0:
                return self._reject("marge_de_risque_epuisee")
            size = min(size, max_risk / dist)
        if size <= 0:
            return self._reject("taille_nulle")
        return TradePlan("long" if long else "short", entry, stop, target, size, size * dist,
                         rr, signal.confidence, signal.pattern_names, equity * c.risk_per_trade)
```
### quantbot/signals/engine.py
```python
"""Agrégation des patterns en un signal unique (direction + confiance)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..config import Settings
from ..indicators.core import ema
from ..logging_utils import get_logger
from ..patterns.base import PatternMatch
from ..patterns.scanner import PatternScanner

log = get_logger("signals")


@dataclass
class Signal:
    direction: str  # bullish | bearish
    confidence: float
    price: float
    atr: float
    timestamp: Any
    matches: list[PatternMatch]
    notes: list[str] = field(default_factory=list)
    stop_price: Optional[float] = None  # stratégies à niveaux propres ; None = stop ATR par défaut
    take_profit_price: Optional[float] = None

    @property
    def pattern_names(self) -> list[str]:
        return [m.name for m in self.matches]


def _trend(df: pd.DataFrame, fast: int, slow: int) -> Optional[str]:
    if len(df) < slow + 1:
        return None
    f, s = ema(df["close"], fast).iloc[-1], ema(df["close"], slow).iloc[-1]
    if not (np.isfinite(f) and np.isfinite(s)):
        return None
    return "bullish" if f > s else "bearish"


class SignalEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.scanner = PatternScanner(settings)

    def evaluate(self, df: pd.DataFrame, htf_df: Optional[pd.DataFrame] = None) -> Optional[Signal]:
        return self.build_signal(df, self.scanner.scan(df), htf_df)

    def build_signal(self, df: pd.DataFrame, matches: list[PatternMatch],
                     htf_df: Optional[pd.DataFrame] = None) -> Optional[Signal]:
        cfg = self.settings.signals
        by_dir: dict[str, list[tuple[float, PatternMatch]]] = {"bullish": [], "bearish": []}
        for m in matches:
            if cfg.require_confirmation and not m.confirmed:
                continue
            weight = cfg.category_weights.get(m.category, 1.0)
            conf = m.score * weight * (1.0 if m.confirmed else cfg.unconfirmed_penalty)
            by_dir[m.direction].append((conf, m))
        best = {d: max((c for c, _ in v), default=0.0) for d, v in by_dir.items()}
        if max(best.values()) <= 0:
            return None
        direction = max(best, key=best.get)
        other = "bearish" if direction == "bullish" else "bullish"
        if best[direction] - best[other] < cfg.min_edge:
            log.debug("Signal ambigu (bull=%.2f bear=%.2f)", best["bullish"], best["bearish"])
            return None

        chosen = sorted(by_dir[direction], key=lambda x: -x[0])
        categories = {m.category for _, m in chosen}
        conf = min(1.0, best[direction] + cfg.confluence_bonus * (len(categories) - 1))
        notes: list[str] = []

        if cfg.trend_filter != "none":
            ref = df if cfg.trend_filter == "ema" else htf_df
            trend = _trend(ref, cfg.ema_fast, cfg.ema_slow) if ref is not None else None
            if trend is not None and trend != direction:
                conf *= cfg.counter_trend_penalty
                notes.append(f"contre-tendance ({cfg.trend_filter})")
        if conf < cfg.min_confidence:
            return None

        ctx = self.scanner.last_context
        atr = float(ctx.atr[-1]) if ctx is not None else float("nan")
        if ctx is not None and cfg.atr_floor_frac > 0:
            ref = float(np.nanmedian(ctx.atr[-200:])) if np.isfinite(ctx.atr[-200:]).any() else float("nan")
            if np.isfinite(ref):
                atr = max(atr, cfg.atr_floor_frac * ref)  # marché vide : pas de stop à 0,001 % du prix
        return Signal(direction, conf, float(df["close"].iloc[-1]), atr, df.index[-1],
                      [m for _, m in chosen[:5]], notes)
```
### quantbot/strategies/events.py
```python
"""Stratégies à règles explicites : événements causaux datés -> signaux pour le moteur unique.

Chaque stratégie est une machine à états qui parcourt les barres dans l'ordre et n'émet un événement à la barre t
qu'avec des données <= t. Garantie testée : générer les événements sur un préfixe des données donne exactement les
mêmes événements que sur la série complète (aucune fuite).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from ..config import Settings
from ..indicators.core import atr_np
from ..patterns.base import PatternMatch
from ..signals.engine import Signal


@dataclass
class Event:
    ts: pd.Timestamp
    direction: str  # bullish | bearish
    stop: float
    target: Optional[float] = None  # None = cible par défaut (reward_risk du risque)
    name: str = ""
    meta: dict = field(default_factory=dict)


def atr_series(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    return atr_np(df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float), period)


class EventSignalEngine:
    """Sert les événements pré-calculés au moteur ; `evaluate` ne regarde que la dernière barre de la fenêtre."""

    def __init__(self, settings: Settings, events: list[Event]) -> None:
        self.settings = settings
        self.by_ts: dict = {}
        for e in events:
            self.by_ts.setdefault(e.ts, e)  # un seul événement par barre (le premier)

    def evaluate(self, window: pd.DataFrame, htf=None) -> Optional[Signal]:
        ev = self.by_ts.get(window.index[-1])
        if ev is None:
            return None
        a = atr_series(window.tail(300), self.settings.detection.atr_period)
        atr = float(a[-1]) if np.isfinite(a[-1]) else float("nan")
        frac = self.settings.signals.atr_floor_frac
        if frac > 0 and np.isfinite(a).any():
            atr = max(atr, frac * float(np.nanmedian(a[-200:])))
        m = PatternMatch(ev.name or "event", "event", ev.direction, 0.9, 0, 1, True, ev.meta)
        return Signal(ev.direction, 0.9, float(window["close"].iloc[-1]), atr, window.index[-1], [m],
                      [ev.name], stop_price=ev.stop, take_profit_price=ev.target)
```
### quantbot/data/mt5.py
```python
"""Export MetaTrader 5 (CSV) : horloge du courtier -> UTC, spreads, trous.

Le CSV fourni contient `time` (= horloge courtier − 3 h FIXE, donc fausse d'1 h en hiver quand le
serveur est en UTC+2) et `time_broker_epoch` (horloge courtier brute). On reconstruit l'UTC avec la
règle des serveurs « fin de journée New York » : UTC+3 pendant l'heure d'été américaine, UTC+2 sinon.
Contrôle de cohérence : la semaine FX doit s'ouvrir dimanche 21:00 UTC (été) / 22:00 UTC (hiver).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..exceptions import DataValidationError
from ..logging_utils import get_logger
from .validation import validate_ohlcv

log = get_logger("data.mt5")


_DST_RULES = {"eu_dst": ("Europe/Athens", pd.Timedelta(hours=3)), "us_dst": ("America/New_York", pd.Timedelta(hours=-4))}


def broker_clock_to_utc(clock: pd.DatetimeIndex, rule: str = "eu_dst") -> pd.DatetimeIndex:
    """Horloge courtier (naïve) -> UTC naïf. UTC+3 en heure d'été, UTC+2 sinon.

    rule='eu_dst' (DÉFAUT) : l'été suit le calendrier EUROPÉEN (mesuré : 98,8 % des pauses quotidiennes de l'or
    reprennent à 18:00 New York, contre 92,5 % avec le calendrier US ; l'écart tient aux ~4 semaines/an où les
    deux calendriers divergent). 'us_dst' : ancien choix des specs v0/v1/v2 (conservé pour reproduire ces essais).
    'fixedN' : décalage fixe.
    """
    clock = pd.DatetimeIndex(clock)
    if rule.startswith("fixed"):
        return clock - pd.Timedelta(hours=int(rule.replace("fixed", "")))
    if rule not in _DST_RULES:
        raise ValueError(f"règle inconnue : {rule}")
    zone, summer_offset = _DST_RULES[rule]
    guess = (clock - pd.Timedelta(hours=3)).tz_localize("UTC")  # hypothèse « été »
    local = guess.tz_convert(zone)
    is_dst = (local.tz_localize(None) - guess.tz_localize(None)) == summer_offset
    return pd.DatetimeIndex(np.where(is_dst, clock - pd.Timedelta(hours=3), clock - pd.Timedelta(hours=2)))


def load_mt5_csv(path: str | Path, rule: str = "eu_dst") -> pd.DataFrame:
    """Charge l'export, index = UTC naïf reconstruit. Colonnes : OHLC, volume (ticks), spread (prix), spread_points."""
    try:
        raw = pd.read_csv(path)
    except FileNotFoundError as exc:
        raise DataValidationError(f"CSV introuvable : {path}") from exc
    need = {"time_broker_epoch", "open", "high", "low", "close"}
    if not need <= set(raw.columns):
        raise DataValidationError(f"Colonnes manquantes : {sorted(need - set(raw.columns))}")
    clock = pd.DatetimeIndex(pd.to_datetime(raw["time_broker_epoch"], unit="s"))
    df = raw[["open", "high", "low", "close"]].copy()
    df["volume"] = raw["tick_volume"] if "tick_volume" in raw else 0.0
    df["spread"] = raw["spread"] if "spread" in raw else 0.0
    df["spread_points"] = raw["spread_points"] if "spread_points" in raw else 0.0
    df.index = broker_clock_to_utc(clock, rule)
    df = df[~df.index.duplicated(keep="last")].sort_index()  # transitions : 1 h ambiguë possible
    out = validate_ohlcv(df[["open", "high", "low", "close", "volume"]], repair=False)
    out["spread"] = df["spread"].to_numpy()[: len(out)] if len(out) == len(df) else df["spread"].reindex(out.index)
    out["spread_points"] = df["spread_points"].reindex(out.index)
    out.attrs.update({"source": f"MT5:{Path(path).name}", "clock_rule": rule})
    return out


def find_holes(df: pd.DataFrame, max_gap_hours: float = 120.0) -> list[dict]:
    """Trous de données (au-delà des week-ends/jours fériés), avec le saut de prix qu'ils cachent."""
    gap_h = df.index.to_series().diff().dt.total_seconds().div(3600.0)
    out = []
    for i in np.flatnonzero(gap_h.to_numpy() > max_gap_hours):
        out.append({"from": str(df.index[i - 1]), "to": str(df.index[i]), "hours": round(float(gap_h.iloc[i]), 1),
                    "price_jump_pct": round(float(df["open"].iloc[i] / df["close"].iloc[i - 1] - 1) * 100, 2)})
    return out


def weekly_open_check(df: pd.DataFrame) -> dict:
    """Heure UTC (décimale) de la première barre de chaque semaine, médiane été vs hiver.

    Pour un instrument FX/CFD qui s'ouvre à 17:00 New York : ~21:00 UTC en été, ~22:00 en hiver (écart d'1 h).
    Un écart nul entre saisons trahit une conversion horaire à décalage fixe.
    """
    s = df.index.to_series()
    key = (s + pd.Timedelta(hours=12)).dt.strftime("%G-%V")  # dimanche soir -> semaine de trading suivante
    wk = s.groupby(key).min()
    hh = wk.dt.hour + wk.dt.minute / 60.0
    mo = wk.dt.month
    summer, winter = hh[mo.isin([6, 7, 8])], hh[mo.isin([12, 1, 2])]
    return {"summer_median_utc": float(summer.median()) if len(summer) else None,
            "winter_median_utc": float(winter.median()) if len(winter) else None,
            "shift_hours": (float(winter.median() - summer.median()) if len(summer) and len(winter) else None)}


def gap_quantile(df: pd.DataFrame, q: float = 0.999, max_gap_hours: float = 120.0) -> float:
    """Quantile q de |ouverture / clôture précédente - 1| (gaps de reprise, week-ends, annonces).

    Les trous de données (> max_gap_hours) sont exclus : ce sont des données manquantes, pas du risque de marché.
    """
    gap_h = df.index.to_series().diff().dt.total_seconds().div(3600.0)
    g = (df["open"] / df["close"].shift(1) - 1.0).abs()[gap_h <= max_gap_hours].dropna()
    return float(g.quantile(q)) if len(g) else float("nan")


def leverage_cap_from_gaps(df: pd.DataFrame, loss_budget: float = 0.01, q: float = 0.999, lo: float = 0.25,
                           hi: float = 5.0, max_gap_hours: float = 120.0) -> float:
    """Levier maximal tel qu'un gap extrême (quantile q) coûte au plus `loss_budget` du capital."""
    g = gap_quantile(df, q, max_gap_hours)
    if not np.isfinite(g) or g <= 0:
        return lo
    return float(min(hi, max(lo, loss_budget / g)))


def costs_from_frame(df: pd.DataFrame, since: str | None = None) -> dict:
    """Spread médian (fraction du prix) mesuré ; None si la colonne n'est pas fiable (>30 % de zéros)."""
    d = df if since is None else df[df.index >= since]
    if "spread" not in d.columns or len(d) == 0:
        return {"spread_frac": None, "reliable": False, "zero_share": None}
    zero = float((d["spread"] <= 0).mean())
    reliable = zero < 0.30
    frac = float((d["spread"] / d["close"]).median()) if reliable else None
    return {"spread_frac": frac, "reliable": reliable, "zero_share": round(zero, 3)}
```
### quantbot/exceptions.py
```python
"""Exceptions propres au projet quantbot."""


class PatternBotError(Exception):
    """Base de toutes les erreurs du projet."""


class ConfigError(PatternBotError):
    """Configuration invalide."""


class DataValidationError(PatternBotError):
    """Données OHLCV invalides."""


class DataFetchError(PatternBotError):
    """Echec de récupération de données externes."""


class ExecutionError(PatternBotError):
    """Erreur d'exécution d'ordre."""


class LiveTradingDisabledError(ExecutionError):
    """Le trading réel n'est pas explicitement autorisé."""


class AIAdapterError(PatternBotError):
    """Echec d'un adaptateur LLM."""


class MemoryStoreError(PatternBotError):
    """Echec de la mémoire d'expériences."""
```
### quantbot/config.py
```python
"""Configuration typée et validée.

Les patterns sont des *heuristiques* : `ToleranceConfig` regroupe les marges
de battement (`tolerance_percentage`, `deviation_threshold`, `min_score`).
Une configuration complète (`Settings`) constitue aussi une « version de
stratégie » que la boucle d'amélioration peut surcharger de façon contrôlée.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

from .exceptions import ConfigError


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)


class _Section:
    @classmethod
    def from_dict(cls, data: Optional[dict]):
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ConfigError(f"{cls.__name__} doit être un objet, reçu {type(data).__name__}")
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ConfigError(f"Clés inconnues dans {cls.__name__} : {sorted(unknown)}")
        obj = cls(**data)
        obj.validate()
        return obj

    def validate(self) -> None:  # pragma: no cover - surchargé
        pass


@dataclass
class ToleranceConfig(_Section):
    tolerance_percentage: float = 0.15  # écart relatif accepté sans pénalité
    deviation_threshold: float = 0.35  # écart relatif au-delà duquel le score tombe à 0
    min_score: float = 0.60  # score minimal pour retenir un pattern

    def validate(self) -> None:
        _require(0 < self.tolerance_percentage < 1, "tolerance_percentage doit être dans ]0,1[")
        _require(
            self.tolerance_percentage < self.deviation_threshold <= 1,
            "deviation_threshold doit être > tolerance_percentage et <= 1",
        )
        _require(0 < self.min_score <= 1, "min_score doit être dans ]0,1]")


@dataclass
class DetectionConfig(_Section):
    pivot_order: int = 3
    atr_period: int = 14
    max_pivot_age: int = 12
    context_bars: int = 5
    context_weight: float = 0.25
    context_move_atr: float = 2.0
    min_height_atr: float = 1.5
    min_bars_between: int = 4
    enabled: Optional[list] = None  # None = tous les détecteurs

    def validate(self) -> None:
        _require(self.pivot_order >= 1, "pivot_order >= 1")
        _require(self.atr_period >= 2, "atr_period >= 2")
        _require(self.max_pivot_age >= 0, "max_pivot_age >= 0")
        _require(self.context_bars >= 1, "context_bars >= 1")
        _require(0 <= self.context_weight < 1, "context_weight dans [0,1[")
        _require(self.context_move_atr > 0, "context_move_atr > 0")
        _require(self.min_height_atr >= 0, "min_height_atr >= 0")
        _require(self.min_bars_between >= 1, "min_bars_between >= 1")
        _require(
            self.enabled is None or all(isinstance(x, str) for x in self.enabled),
            "enabled doit être None ou une liste de noms",
        )


@dataclass
class SignalConfig(_Section):
    min_confidence: float = 0.55
    category_weights: dict = field(
        default_factory=lambda: {"candle": 0.8, "chart": 1.0, "harmonic": 0.9}
    )
    unconfirmed_penalty: float = 0.8
    require_confirmation: bool = False
    min_edge: float = 0.10
    confluence_bonus: float = 0.05
    trend_filter: str = "none"  # none | ema | htf
    ema_fast: int = 20
    ema_slow: int = 50
    counter_trend_penalty: float = 0.6
    htf_rule: str = "4h"
    atr_floor_frac: float = 0.0  # 0 = désactivé ; sinon ATR utilisé >= frac x ATR médian récent (marché mince)

    def validate(self) -> None:
        _require(0 < self.min_confidence <= 1, "min_confidence dans ]0,1]")
        _require(all(v >= 0 for v in self.category_weights.values()), "poids négatifs interdits")
        _require(0 < self.unconfirmed_penalty <= 1, "unconfirmed_penalty dans ]0,1]")
        _require(self.min_edge >= 0 and self.confluence_bonus >= 0, "min_edge/confluence_bonus >= 0")
        _require(self.trend_filter in {"none", "ema", "htf"}, "trend_filter: none|ema|htf")
        _require(1 <= self.ema_fast < self.ema_slow, "ema_fast < ema_slow")
        _require(0 <= self.atr_floor_frac <= 2, "atr_floor_frac dans [0,2]")
        _require(0 < self.counter_trend_penalty <= 1, "counter_trend_penalty dans ]0,1]")


@dataclass
class RiskConfig(_Section):
    risk_per_trade: float = 0.01
    atr_stop_mult: float = 1.5
    reward_risk: float = 2.0
    min_reward_risk: float = 1.3
    max_leverage: float = 3.0
    max_daily_loss: float = 0.03
    max_trades_per_day: int = 5
    flat_before_weekend: bool = False  # clôture + pas d'entrée du vendredi soir au dimanche (gaps de réouverture)
    weekend_cutoff_hour: int = 20  # heure locale (session_tz) du vendredi
    session_tz: str = "Europe/Prague"
    min_stop_atr: float = 0.0  # 0 = désactivé ; sinon distance de stop >= min_stop_atr x ATR (jamais de stop à 0,001 % du prix)
    max_cost_r: float = 0.0  # 0 = désactivé ; sinon refuse l'entrée si coût aller-retour / distance de stop > ce seuil (en R)
    session_utc_start: int = 0  # fenêtre d'entrée [start, end[ en heures UTC (scalping : heures liquides)
    session_utc_end: int = 24

    def validate(self) -> None:
        _require(self.max_cost_r >= 0 and self.min_stop_atr >= 0, "max_cost_r, min_stop_atr >= 0")
        _require(0 <= self.session_utc_start < self.session_utc_end <= 24, "fenêtre UTC : 0 <= start < end <= 24")
        _require(0 <= self.weekend_cutoff_hour <= 23, "weekend_cutoff_hour dans [0,23]")
        _require(0 < self.risk_per_trade <= 0.1, "risk_per_trade dans ]0,0.1]")
        _require(self.atr_stop_mult > 0, "atr_stop_mult > 0")
        _require(0 < self.min_reward_risk <= self.reward_risk, "0 < min_reward_risk <= reward_risk")
        _require(self.max_leverage > 0, "max_leverage > 0")
        _require(0 < self.max_daily_loss <= 1, "max_daily_loss dans ]0,1]")
        _require(self.max_trades_per_day >= 1, "max_trades_per_day >= 1")


@dataclass
class BacktestConfig(_Section):
    initial_equity: float = 10_000.0
    warmup_bars: int = 100
    window_bars: int = 300
    max_hold_bars: int = 100
    max_gap_hours: float = 120.0  # trou de données plus long : position clôturée, contexte réinitialisé

    def validate(self) -> None:
        _require(self.max_gap_hours > 0, "max_gap_hours > 0")
        _require(self.initial_equity > 0, "initial_equity > 0")
        _require(self.warmup_bars >= 50, "warmup_bars >= 50")
        _require(self.window_bars >= self.warmup_bars, "window_bars >= warmup_bars")
        _require(self.max_hold_bars >= 1, "max_hold_bars >= 1")


@dataclass
class ExecutionConfig(_Section):
    mode: str = "paper"  # paper | live
    allow_live: bool = False  # double verrou, avec QUANTBOT_ALLOW_LIVE=1
    fee_rate: float = 0.0005
    slippage: float = 0.0002
    spread: float = 0.0
    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    live_auto_adopt: bool = False  # en live, une nouvelle version doit être approuvée à la main
    mt5_symbol: str = "EURUSD"
    mt5_timeframe: str = "H1"
    mt5_server_utc_offset_hours: int = 0  # décalage de l'heure serveur MT5 par rapport à UTC
    mt5_magic: int = 20260101
    mt5_deviation_points: int = 20

    def validate(self) -> None:
        _require(self.mode in {"paper", "live"}, "mode: paper|live")
        _require(self.fee_rate >= 0 and self.slippage >= 0 and self.spread >= 0, "coûts >= 0")


@dataclass
class FtmoConfig(_Section):
    """Règles FTMO 2-Step (valeurs à vérifier sur ftmo.com : elles peuvent changer)."""

    enabled: bool = False
    phase: str = "challenge"  # challenge | verification
    initial_balance: float = 100_000.0
    profit_target_challenge: float = 0.10
    profit_target_verification: float = 0.05
    max_daily_loss: float = 0.05
    max_total_loss: float = 0.10
    daily_loss_buffer: float = 0.01  # arrêt interne à 4 % de perte journalière
    total_loss_buffer: float = 0.02  # arrêt interne à 8 % de perte totale
    min_trading_days: int = 4
    timezone: str = "Europe/Prague"  # minuit CE(S)T = reset de la limite journalière
    flat_before_weekend: bool = True
    weekend_cutoff_hour: int = 20
    news_blackouts: list = field(default_factory=list)  # [["iso_debut", "iso_fin"], ...]
    stop_after_target: bool = True
    max_risk_per_trade: float = 0.005
    expected_login: Optional[int] = None  # refuse de trader sur un autre compte MT5

    def validate(self) -> None:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        _require(self.phase in {"challenge", "verification"}, "phase: challenge|verification")
        _require(self.initial_balance > 0, "initial_balance > 0")
        _require(0 < self.max_daily_loss < self.max_total_loss < 1, "0 < max_daily_loss < max_total_loss < 1")
        _require(0 <= self.daily_loss_buffer < self.max_daily_loss, "daily_loss_buffer < max_daily_loss")
        _require(0 <= self.total_loss_buffer < self.max_total_loss, "total_loss_buffer < max_total_loss")
        _require(0 < self.max_risk_per_trade <= 0.02, "max_risk_per_trade dans ]0,0.02]")
        _require(self.min_trading_days >= 0 and 0 <= self.weekend_cutoff_hour <= 23, "jours/heure invalides")
        for w in self.news_blackouts:
            _require(isinstance(w, (list, tuple)) and len(w) == 2, "news_blackouts: paires [debut, fin]")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(f"Fuseau inconnu : {self.timezone}") from exc


@dataclass
class ValidationConfig(_Section):
    split: tuple = (0.6, 0.2, 0.2)  # in-sample / out-of-sample / test final
    min_trades: int = 20
    min_profit_factor: float = 1.1
    max_drawdown: float = 0.30
    walk_forward_windows: int = 4
    min_wf_positive_ratio: float = 0.5
    robustness_jitter: float = 0.15  # variation ± des paramètres testés
    min_robust_ratio: float = 0.6  # part des voisins qui doivent rester rentables
    cost_stress_multiplier: float = 2.0
    min_improvement: float = 0.0  # gain minimal vs version courante (score OOS)

    def __post_init__(self) -> None:
        self.split = tuple(self.split)

    def validate(self) -> None:
        _require(len(self.split) == 3 and abs(sum(self.split) - 1.0) < 1e-9, "split: 3 parts sommant à 1")
        _require(all(p > 0 for p in self.split), "split: parts > 0")
        _require(self.min_trades >= 1, "min_trades >= 1")
        _require(0 < self.max_drawdown <= 1, "max_drawdown dans ]0,1]")
        _require(self.walk_forward_windows >= 2, "walk_forward_windows >= 2")
        _require(0 < self.robustness_jitter < 1, "robustness_jitter dans ]0,1[")
        _require(self.cost_stress_multiplier >= 1, "cost_stress_multiplier >= 1")


@dataclass
class AIConfig(_Section):
    enabled: bool = False
    veto_enabled: bool = False
    claude_model: str = "claude-sonnet-5-5"
    chatgpt_model: str = "gpt-4o"
    gemini_model: str = "gemini-2.5-flash"
    timeout_s: float = 30.0

    def validate(self) -> None:
        _require(self.timeout_s > 0, "timeout_s > 0")


@dataclass
class LoggingConfig(_Section):
    level: str = "INFO"
    file: Optional[str] = None


_SECTIONS = {
    "tolerance": ToleranceConfig,
    "detection": DetectionConfig,
    "signals": SignalConfig,
    "risk": RiskConfig,
    "backtest": BacktestConfig,
    "execution": ExecutionConfig,
    "ftmo": FtmoConfig,
    "validation": ValidationConfig,
    "ai": AIConfig,
    "logging": LoggingConfig,
}


@dataclass
class Settings:
    tolerance: ToleranceConfig = field(default_factory=ToleranceConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    signals: SignalConfig = field(default_factory=SignalConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    ftmo: FtmoConfig = field(default_factory=FtmoConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "Settings":
        data = data or {}
        if not isinstance(data, dict):
            raise ConfigError("La configuration doit être un objet JSON")
        unknown = set(data) - set(_SECTIONS)
        if unknown:
            raise ConfigError(f"Sections inconnues : {sorted(unknown)}")
        return cls(**{name: klass.from_dict(data.get(name)) for name, klass in _SECTIONS.items()})

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self)))

    def with_overrides(self, overrides: dict[str, Any]) -> "Settings":
        """Copie validée avec surcharges 'section.cle' -> valeur."""
        data = self.to_dict()
        for dotted, value in overrides.items():
            section, _, key = dotted.partition(".")
            if section not in data or key not in data[section]:
                raise ConfigError(f"Paramètre inconnu : {dotted}")
            data[section][key] = value
        return Settings.from_dict(data)


def load_settings(path: Optional[str | Path] = None) -> Settings:
    if path is None:
        return Settings()
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Fichier de config introuvable : {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON invalide dans {path} : {exc}") from exc
    return Settings.from_dict(raw)


def save_settings(settings: Settings, path: str | Path) -> None:
    Path(path).write_text(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

### Faux terminal MT5 utilisé par les tests existants (étends-le pour tes tests)
```python
class FakeMT5:
    TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ORDER_TYPE_SELL = 1, 0, 1
    ORDER_TIME_GTC, ORDER_FILLING_IOC, TRADE_RETCODE_DONE = 0, 1, 10009

    def __init__(self, login=1234, currency="USD", profit_ccy="USD", retcode=10009, volume_min=0.01):
        self.acct = NS(login=login, currency=currency, server="FTMO-Demo", balance=100_000.0, equity=100_000.0)
        self.info = NS(currency_profit=profit_ccy, trade_contract_size=100_000, volume_step=0.01,
                       volume_min=volume_min, volume_max=50.0)
        self.retcode, self.sent, self.open_positions, self.deals = retcode, [], [], []

    def initialize(self): return True
    def last_error(self): return (1, "x")
    def account_info(self): return self.acct
    def symbol_info(self, s): return self.info
    def symbol_select(self, s, e): return True
    def symbol_info_tick(self, s): return NS(ask=1.1002, bid=1.1000)
    def positions_get(self, symbol=None): return list(self.open_positions)
    def history_deals_get(self, position=None): return self.deals

    def order_send(self, req):
        self.sent.append(req)
        if self.retcode == self.TRADE_RETCODE_DONE and "position" not in req:
            self.open_positions = [NS(ticket=77, magic=req["magic"])]
        elif "position" in req:
            self.open_positions = []
            self.deals = [NS(profit=25.0, commission=-3.5, swap=0.0, fee=0.0, price=1.101)]
        return NS(retcode=self.retcode, comment="ok", price=req["price"])
```

# PREMIÈRE ACTION
Ne code rien tout de suite. Réponds d'abord par : (a) ta compréhension en 10 lignes de ce qui est demandé et de ce qui est interdit, (b) les 5 risques d'exécution les plus dangereux que tu identifies dans le code fourni (en particulier dans `MT5Broker`), (c) tes questions éventuelles. Puis attends mon « go » pour T1.
