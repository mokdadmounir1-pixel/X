# RÔLE
Tu es un ingénieur logiciel senior (Python, MetaTrader 5, Windows, sûreté d'exécution). Tu **connectes** un bot de trading déjà écrit à un **vrai** terminal MetaTrader 5 (compte DÉMO) et tu produis les preuves que seul un vrai terminal peut fournir. Tu écris du code Python 3.10+ simple, commenté en français. Ton code sera relu par un autre ingénieur (Claude) avant tout usage.

# CONTEXTE
Projet « quantbot ». La logique du bot est ÉCRITE et testée **contre un faux terminal** (code ci-dessous, dossier `quantbot/live/`) : état persistant, coupe-circuit, flux de barres, broker MT5 durci, boucle de trading, approbation humaine. **Cela prouve la logique, pas le comportement réel du courtier.** Ton travail : la connexion réelle et la vérification sur le vrai terminal.
- **Aucune stratégie n'a été validée à ce jour.** Le bot est donc INERTE par défaut : sans fichier `approved_strategies.json` écrit à la main par l'utilisateur, il reste en OBSERVATION (aucun ordre envoyé).
- Le moteur de trading et la validation sont dans d'autres fichiers que tu n'as pas à voir ni à modifier.

# RÈGLES ABSOLUES
1. **Rien de factice dans le chemin d'exécution** : le code que tu écris ne doit parler QU'AU VRAI module `MetaTrader5`. Aucun faux terminal, aucune donnée simulée, aucun résultat inventé. Le faux terminal ci-dessous sert aux tests uniquement et ne doit JAMAIS être importé par un script d'exploitation.
2. **Aucun appel à `order_send` dans les scripts de diagnostic.** `order_check` est autorisé (il ne passe aucun ordre) ; `order_send` n'apparaît que dans `quantbot/live/mt5_exec.py`, que tu ne modifies pas sans me le signaler explicitement.
3. **Ne modifie PAS** la logique de sécurité existante (coupe-circuit, write-ahead, `order_check` obligatoire, approbation, refus de compte non démo). Si tu penses qu'elle est fausse ou incomplète, **dis-le et explique**, ne la contourne pas.
4. **Ne demande JAMAIS** identifiant, mot de passe, numéro de compte complet ou serveur. Les sorties de diagnostic masquent le numéro de compte (garde les 2 derniers chiffres).
5. **Aucun accès réseau** hors terminal MT5 local.
6. **Honnêteté** : si une valeur du terminal contredit une hypothèse du code (fuseau horaire, mode de remplissage, niveau d'arrêt minimal, taille de lot, nom du symbole, retcode inattendu…), **rapporte-la telle quelle**, ne l'arrange pas pour que le code « marche ». Ne prétends jamais qu'une chose « a été testée sur MT5 » sans en fournir la sortie réelle.
7. Pas de martingale, pas de grille, pas de levier, pas de position sans stop — rien de ce type ne doit être introduit.

# TÂCHES (une par message ; attends « suivant »)
C1. `scripts/mt5_selfcheck.py` — diagnostic en LECTURE SEULE sur le vrai terminal, sortie JSON (à me renvoyer) :
  - `initialize()`, version du terminal, mode du compte (`trade_mode` : démo/réel/concours), devise, levier, serveur (nom), login masqué ;
  - pour le symbole choisi : `digits`, `point`, `trade_contract_size`, `volume_min/step/max`, `filling_mode` (décodé : FOK/IOC/RETURN), `trade_stops_level`, `trade_freeze_level`, `trade_mode` du symbole, `currency_profit`, spread courant, sessions de trading si disponibles ;
  - **fuseau** : compare l'heure du dernier tick (`symbol_info_tick().time`) à l'heure UTC système, en déduit le décalage courtier (heures) ;
  - **sémantique des barres** : `copy_rates_from_pos(sym, tf, 0, 3)` vs `(sym, tf, 1, 3)` — confirme que la position 0 est la barre en formation (son `time` est égal à l'ouverture de la période en cours) ;
  - **`order_check` seulement** (JAMAIS `order_send`) sur un ordre d'achat minimal hypothétique (volume minimal, SL et TP valides, mode de remplissage détecté) : rapporte `retcode`, `comment`, marge requise ;
  - rapport final lisible + JSON, incluant TOUT écart avec les hypothèses listées dans le code (`quantbot/live/*.py`).
C2. `scripts/run_live.py` — lanceur RÉEL : importe `MetaTrader5`, construit `LiveRunner` (voir code), options `--symbol`, `--strategy`, `--spec`, `--approvals`, `--state`, `--kill-file`, `--poll`, `--servers` (liste blanche) ; affiche clairement le MODE (OBSERVATION ou DEMO_ACTIF) et la raison ; sous-commandes `--status` (lit l'état, n'envoie rien), `--kill` (crée le fichier KILL), `--clear-kill` (exige de taper `JE_COMPRENDS`) ; gère Ctrl+C proprement.
C3. Endpoint `GET /api/live` dans `quantbot/ui/server.py` : lecture SEULE de la base d'état (connexion SQLite en `mode=ro`), chemin via la variable d'environnement `QUANTBOT_STATE`, serveur lié à 127.0.0.1 UNIQUEMENT ; renvoie mode, raison, dernière barre, âge du battement de cœur, raisons du coupe-circuit, 20 dernières intentions, 30 derniers événements. Ajoute un onglet « En direct » à `index.html` (même style, aucun framework). Tests pytest (créer un état avec `StateStore`, interroger l'endpoint).
C4. `docs/EXPLOITATION.md` — guide en français pour un non-développeur : prérequis Windows, installation, ordre des opérations (1. `mt5_selfcheck`, 2. OBSERVATION plusieurs jours, 3. seulement ensuite envisager l'approbation), comment écrire `approved_strategies.json` (et pourquoi c'est une décision humaine, avec l'empreinte de spec), que faire en cas d'état INCONNU, comment arrêter, comment reprendre, planificateur de tâches Windows pour le relancer (sans jamais contourner le coupe-circuit).
C5. Revue critique : liste précise de ce que le faux terminal ne peut PAS prouver et des vérifications à faire sur le vrai terminal avant tout passage en DEMO_ACTIF (chacune avec la commande à lancer et la sortie attendue).

# ATTENDU À CHAQUE TÂCHE
(1) fichiers créés/modifiés, (2) code complet, (3) tests (sans terminal pour C3), (4) **ce qui n'a pas pu être testé et pourquoi**, (5) risques résiduels.
Si une exigence est ambiguë ou te semble dangereuse, **pose la question avant de coder**.

# PREMIÈRE ACTION
Ne code rien. Réponds par : (a) ta compréhension en 8 lignes, (b) les 5 points où le faux terminal pourrait te tromper sur le comportement d'un vrai terminal MT5 (relis `tests/fake_mt5_live.py`), (c) tes questions. Puis attends « go ».

# CODE EXISTANT (à utiliser tel quel)

### quantbot/live/state.py
```python
"""État persistant du bot en direct (SQLite) : intentions d'ordres, événements, clé/valeur.

Principe write-ahead : une intention est ÉCRITE (statut PENDING) AVANT tout appel à order_send. Au redémarrage, une
intention PENDING/SENT/UNKNOWN est réconciliée avec le terminal : jamais rejouée à l'aveugle.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from ..exceptions import MemoryStoreError

# PENDING -> SENT -> CONFIRMED ; REFUSED (order_check/serveur) ; FAILED (erreur avant envoi) ; UNKNOWN (réponse ambiguë)
OPEN_STATUSES = ("PENDING", "SENT", "UNKNOWN")
SCHEMA = """
CREATE TABLE IF NOT EXISTS intents (
  id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL, kind TEXT NOT NULL, side TEXT,
  status TEXT NOT NULL, plan TEXT, detail TEXT, ticket INTEGER, strategy TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, level TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class StateStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        try:
            self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.executescript(SCHEMA)
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Ouverture de l'état impossible ({path}) : {exc}") from exc

    def _x(self, sql: str, params: tuple = ()):
        with self._lock:
            try:
                return self.db.execute(sql, params)
            except sqlite3.Error as exc:
                raise MemoryStoreError(f"Écriture d'état échouée : {exc}") from exc

    # --- intentions ----------------------------------------------------------
    def new_intent(self, kind: str, side: str, plan: dict, strategy: str = "") -> str:
        iid = uuid.uuid4().hex[:16]
        now = time.time()
        self._x("INSERT INTO intents (id,created,updated,kind,side,status,plan,strategy) VALUES (?,?,?,?,?,?,?,?)",
                (iid, now, now, kind, side, "PENDING", json.dumps(plan, default=str), strategy))
        return iid

    def mark(self, iid: str, status: str, detail: str = "", ticket: Optional[int] = None) -> None:
        self._x("UPDATE intents SET status=?, detail=?, updated=?, ticket=COALESCE(?, ticket) WHERE id=?",
                (status, detail[:500], time.time(), ticket, iid))

    def intent(self, iid: str) -> Optional[dict]:
        r = self._x("SELECT * FROM intents WHERE id=?", (iid,)).fetchone()
        return dict(r) if r else None

    def open_intents(self) -> list[dict]:
        q = ",".join("?" * len(OPEN_STATUSES))
        return [dict(r) for r in self._x(f"SELECT * FROM intents WHERE status IN ({q}) ORDER BY created", OPEN_STATUSES).fetchall()]

    def unknown_intents(self) -> list[dict]:
        return [dict(r) for r in self._x("SELECT * FROM intents WHERE status='UNKNOWN' ORDER BY created").fetchall()]

    def recent_intents(self, n: int = 20) -> list[dict]:
        return [dict(r) for r in self._x("SELECT * FROM intents ORDER BY created DESC LIMIT ?", (n,)).fetchall()]

    def known_tickets(self) -> set[int]:
        return {r[0] for r in self._x("SELECT ticket FROM intents WHERE ticket IS NOT NULL").fetchall()}

    # --- clé/valeur & événements ----------------------------------------------
    def set(self, key: str, value: Any) -> None:
        self._x("INSERT INTO kv (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, default=str)))

    def get(self, key: str, default: Any = None) -> Any:
        r = self._x("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def delete(self, key: str) -> None:
        self._x("DELETE FROM kv WHERE key=?", (key,))

    def log(self, level: str, kind: str, detail: str = "") -> None:
        self._x("INSERT INTO events (ts,level,kind,detail) VALUES (?,?,?,?)", (time.time(), level, kind, detail[:500]))

    def recent_events(self, n: int = 30) -> list[dict]:
        return [dict(r) for r in self._x("SELECT * FROM events ORDER BY id DESC LIMIT ?", (n,)).fetchall()]

    def close(self) -> None:
        self.db.close()
```
### quantbot/live/killswitch.py
```python
"""Arrêt d'urgence : tant qu'il est actif, AUCUNE nouvelle entrée n'est possible.

Causes : fichier KILL présent, drapeau persistant (déclenché par le programme), intention à l'état INCONNU non résolue,
limite FTMO atteinte. Il ne se lève jamais seul : seule une action humaine explicite (`clear`) le fait.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .state import StateStore


class KillSwitch:
    def __init__(self, state: StateStore, kill_file: str | Path = "KILL") -> None:
        self.state = state
        self.kill_file = Path(kill_file)

    def reasons(self) -> list[str]:
        out = []
        if self.kill_file.exists():
            out.append(f"fichier {self.kill_file.name} présent")
        flag = self.state.get("kill")
        if flag:
            out.append(f"déclenché : {flag}")
        unk = self.state.unknown_intents()
        if unk:
            out.append(f"{len(unk)} intention(s) à l'état INCONNU non résolue(s)")
        return out

    def active(self) -> bool:
        return bool(self.reasons())

    def trigger(self, reason: str) -> None:
        if not self.state.get("kill"):
            self.state.set("kill", reason)
            self.state.log("CRITICAL", "killswitch", reason)

    def clear(self, confirm: str) -> None:
        """Action HUMAINE : lève le drapeau persistant (pas le fichier KILL ni les intentions INCONNUES, à traiter à la main)."""
        if confirm != "JE_COMPRENDS":
            raise PermissionError("confirmation explicite requise")
        self.state.delete("kill")
        self.state.log("WARNING", "killswitch_clear", "levé par un humain")
```
### quantbot/live/feed.py
```python
"""Flux de barres MT5 : barres CLÔTURÉES uniquement, chacune émise une seule fois, trous et flux figés détectés."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from ..data.mt5 import broker_clock_to_utc
from ..exceptions import DataFetchError
from ..logging_utils import get_logger

log = get_logger("live.feed")


@dataclass
class FeedStatus:
    last_bar: Optional[pd.Timestamp] = None
    stale: bool = False
    hole: Optional[tuple] = None


class BarFeed:
    def __init__(self, mt5: Any, symbol: str, timeframe: str = "M15", n_bars: int = 3000, rule: str = "eu_dst",
                 max_gap_hours: float = 120.0, stale_after_s: float = 1800.0, clock=time.time) -> None:
        self.mt5, self.symbol, self.tf_name, self.n_bars, self.rule = mt5, symbol, timeframe, n_bars, rule
        self.max_gap_hours, self.stale_after_s, self.clock = max_gap_hours, stale_after_s, clock
        tf = getattr(mt5, f"TIMEFRAME_{timeframe}", None)
        if tf is None:
            raise DataFetchError(f"Timeframe MT5 inconnu : {timeframe}")
        self.tf = tf
        self.status = FeedStatus()
        self._last_emitted: Optional[pd.Timestamp] = None
        self._last_new_at = clock()

    def _fetch(self) -> pd.DataFrame:
        # position 1 : la barre 0 (en formation) n'est JAMAIS lue ; aucune décision n'est prise sur une bougie ouverte
        rates = self.mt5.copy_rates_from_pos(self.symbol, self.tf, 1, self.n_bars)
        if rates is None or len(rates) == 0:
            raise DataFetchError(f"Aucune barre {self.symbol} {self.tf_name} : {self.mt5.last_error()}")
        raw = pd.DataFrame(list(rates))
        raw = raw.drop_duplicates("time").sort_values("time")
        clock = pd.DatetimeIndex(pd.to_datetime(raw["time"], unit="s"))
        df = pd.DataFrame({"open": raw["open"].to_numpy(float), "high": raw["high"].to_numpy(float), "low": raw["low"].to_numpy(float),
                           "close": raw["close"].to_numpy(float), "volume": raw["tick_volume"].to_numpy(float),
                           "spread_points": raw.get("spread", pd.Series(0, index=raw.index)).to_numpy(float)},
                          index=broker_clock_to_utc(clock, self.rule))
        return df[~df.index.duplicated(keep="last")].sort_index()

    def poll(self) -> Optional[pd.DataFrame]:
        """Retourne le DataFrame complet des barres clôturées s'il contient au moins UNE barre nouvelle, sinon None."""
        df = self._fetch()
        last = df.index[-1]
        gap = df.index.to_series().diff().dt.total_seconds().div(3600.0)
        holes = gap[gap > self.max_gap_hours]
        self.status.hole = (str(holes.index[-1]), float(holes.iloc[-1])) if len(holes) else None
        if self._last_emitted is not None and last <= self._last_emitted:
            self.status.stale = (self.clock() - self._last_new_at) > self.stale_after_s
            self.status.last_bar = self._last_emitted
            return None
        self._last_new_at = self.clock()
        self.status.stale = False
        self.status.last_bar = last
        return df

    def new_bars(self, df: pd.DataFrame) -> list[pd.Timestamp]:
        """Barres nouvelles de `df` depuis la dernière émission (ordre chronologique) ; marque ces barres comme émises."""
        if self._last_emitted is None:
            new = [df.index[-1]]  # démarrage : on ne rejoue pas l'historique, seule la dernière barre est « nouvelle »
        else:
            new = [t for t in df.index if t > self._last_emitted]
        self._last_emitted = df.index[-1]
        return new
```
### quantbot/live/mt5_exec.py
```python
"""Broker MT5 DURCI pour le bot en direct.

Règles : coupe-circuit vérifié avant toute entrée ; intention écrite AVANT envoi (write-ahead) ; `order_check` obligatoire ;
mode de remplissage détecté ; stop ET cible posés à l'envoi ; retry borné SEULEMENT pour requote/prix changé (même intention) ;
réponse ambiguë => état INCONNU + coupe-circuit + AUCUN renvoi ; compte non démo refusé sans triple autorisation.
"""
from __future__ import annotations

import math
import os
from typing import Any, Optional

from ..config import ExecutionConfig, FtmoConfig
from ..exceptions import ExecutionError, LiveTradingDisabledError
from ..execution.broker import Broker, Position, Trade
from ..logging_utils import get_logger
from ..risk.manager import TradePlan
from .killswitch import KillSwitch
from .state import StateStore

log = get_logger("live.mt5_exec")


class HardenedMT5Broker(Broker):
    manages_exits = True

    def __init__(self, execution: ExecutionConfig, ftmo: FtmoConfig, mt5: Any, state: StateStore, kill: KillSwitch,
                 strategy: str = "", allowed_servers: tuple = (), allow_real: bool = False, max_retries: int = 2) -> None:
        self.cfg, self.mt5, self.state, self.kill, self.strategy, self.max_retries = execution, mt5, state, kill, strategy, max_retries
        self.symbol = execution.mt5_symbol
        self.position: Optional[Position] = None
        self.trades: list[Trade] = []
        self._ticket: Optional[int] = None
        if not mt5.initialize():
            raise ExecutionError(f"Initialisation MT5 impossible : {mt5.last_error()}")
        acct = mt5.account_info()
        if acct is None:
            raise ExecutionError("Compte MT5 introuvable (terminal connecté ?)")
        demo = acct.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
        if not demo and not (allow_real and execution.allow_live and ftmo.enabled and os.environ.get("QUANTBOT_ALLOW_LIVE") == "1"):
            raise LiveTradingDisabledError("Compte NON démo : refus (autorisation réelle = allow_real + allow_live + ftmo.enabled + QUANTBOT_ALLOW_LIVE=1)")
        if allowed_servers and acct.server not in allowed_servers:
            raise ExecutionError(f"Serveur « {acct.server} » hors liste blanche {list(allowed_servers)}")
        if ftmo.expected_login is not None and acct.login != ftmo.expected_login:
            raise ExecutionError(f"Compte {acct.login} différent du compte attendu")
        info = mt5.symbol_info(self.symbol)
        if info is None or not mt5.symbol_select(self.symbol, True):
            raise ExecutionError(f"Symbole MT5 indisponible : {self.symbol}")
        if getattr(info, "currency_profit", acct.currency) != acct.currency:
            raise ExecutionError(f"{self.symbol} coté en {info.currency_profit}, compte en {acct.currency} : conversion non supportée")
        self.demo = demo
        state.log("INFO", "broker_init", f"compte={acct.login} serveur={acct.server} démo={demo}")

    # --- état du compte --------------------------------------------------------------------------
    def balance(self) -> float: return float(self.mt5.account_info().balance)
    def equity(self, mark_price=None) -> float: return float(self.mt5.account_info().equity)

    # --- utilitaires ---------------------------------------------------------------------------------
    def _guard(self) -> None:
        reasons = self.kill.reasons()
        if reasons:
            raise ExecutionError("coupe-circuit actif : " + "; ".join(reasons))

    def _filling(self) -> int:
        """Mode de remplissage supporté par le symbole (jamais IOC en dur)."""
        m, flags = self.mt5, getattr(self.mt5.symbol_info(self.symbol), "filling_mode", 0)
        if flags & m.SYMBOL_FILLING_IOC:
            return m.ORDER_FILLING_IOC
        if flags & m.SYMBOL_FILLING_FOK:
            return m.ORDER_FILLING_FOK
        return m.ORDER_FILLING_RETURN

    def _lots(self, units: float) -> float:
        info = self.mt5.symbol_info(self.symbol)
        step = info.volume_step or 0.01
        lots = round(min(math.floor(units / info.trade_contract_size / step + 1e-9) * step, info.volume_max), 8)
        if lots < info.volume_min:
            raise ExecutionError(f"Taille {units:.2f} u. < volume minimum ({info.volume_min} lot)")
        return lots

    def _find(self, comment: str) -> Optional[Any]:
        for p in self.mt5.positions_get(symbol=self.symbol) or ():
            if p.magic == self.cfg.mt5_magic and getattr(p, "comment", "") == comment:
                return p
        return None

    def _codes(self):
        m = self.mt5
        return (m.TRADE_RETCODE_DONE, {m.TRADE_RETCODE_REQUOTE, m.TRADE_RETCODE_PRICE_CHANGED},
                {m.TRADE_RETCODE_TIMEOUT, m.TRADE_RETCODE_CONNECTION})

    def _ambiguous(self, iid: str, why: str) -> None:
        self.state.mark(iid, "UNKNOWN", why)
        self.kill.trigger(f"réponse ambiguë (intention {iid}) : {why}")

    # --- ouverture ------------------------------------------------------------------------------------
    def open_position(self, plan: TradePlan, market_price: float, ts: Any, idx: int = 0) -> Position:
        self._guard()
        if self.position is not None:
            raise ExecutionError("Position déjà ouverte")
        if not (plan.stop > 0 and plan.take_profit > 0):
            raise ExecutionError("Stop et cible obligatoires")
        m = self.mt5
        iid = self.state.new_intent("OPEN", plan.side, {k: getattr(plan, k) for k in ("side", "entry", "stop", "take_profit", "size", "risk_amount")}, self.strategy)
        done, transient, ambiguous = self._codes()
        try:
            lots = self._lots(plan.size)
        except ExecutionError as exc:
            self.state.mark(iid, "FAILED", str(exc)); raise
        digits = getattr(m.symbol_info(self.symbol), "digits", 5)
        comment = f"qb:{iid}"
        for attempt in range(self.max_retries + 1):
            tick = m.symbol_info_tick(self.symbol)
            if tick is None:
                self.state.mark(iid, "FAILED", "pas de cotation"); raise ExecutionError("Pas de cotation")
            long = plan.side == "long"
            req = {"action": m.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": lots,
                   "type": m.ORDER_TYPE_BUY if long else m.ORDER_TYPE_SELL, "price": float(tick.ask if long else tick.bid),
                   "sl": round(float(plan.stop), digits), "tp": round(float(plan.take_profit), digits),
                   "deviation": self.cfg.mt5_deviation_points, "magic": self.cfg.mt5_magic, "comment": comment,
                   "type_time": m.ORDER_TIME_GTC, "type_filling": self._filling()}
            chk = m.order_check(req)
            if chk is None or chk.retcode not in (0, done):
                self.state.mark(iid, "REFUSED", f"order_check: {getattr(chk, 'retcode', None)} {getattr(chk, 'comment', '')}")
                raise ExecutionError(f"order_check refusé : {getattr(chk, 'retcode', None)}")
            self.state.mark(iid, "SENT", f"tentative {attempt}")
            res = m.order_send(req)
            if res is None or res.retcode in ambiguous:
                self._ambiguous(iid, "réponse absente/ambiguë à l'envoi")
                found = self._find(comment)  # le serveur a peut-être exécuté : on le vérifie, on ne renvoie JAMAIS
                if found is None:
                    raise ExecutionError("État INCONNU : ordre peut-être exécuté ; coupe-circuit actif, réconciliation humaine requise")
                self.state.mark(iid, "CONFIRMED", "résolu par réconciliation", int(found.ticket))
                self.state.log("WARNING", "ambiguite_resolue", "position retrouvée ; le coupe-circuit RESTE actif (levée humaine uniquement)")
                return self._adopt(plan, float(found.price_open), lots, ts, idx, int(found.ticket))
            if res.retcode == done:
                self.state.mark(iid, "CONFIRMED", "exécuté", int(getattr(res, "order", 0)) or None)
                pos = self._find(comment)
                ticket = int(pos.ticket) if pos is not None else int(getattr(res, "order", 0) or 0)
                return self._adopt(plan, float(res.price or req["price"]), lots, ts, idx, ticket)
            if res.retcode in transient and attempt < self.max_retries:
                self.state.log("WARNING", "retry", f"retcode {res.retcode}, intention {iid}")
                continue
            self.state.mark(iid, "REFUSED", f"retcode {res.retcode} {getattr(res, 'comment', '')}")
            raise ExecutionError(f"order_send refusé : {res.retcode}")
        raise ExecutionError("tentatives épuisées")

    def _adopt(self, plan: TradePlan, price: float, lots: float, ts: Any, idx: int, ticket: int) -> Position:
        contract = self.mt5.symbol_info(self.symbol).trade_contract_size
        self._ticket = ticket
        self.position = Position(plan.side, price, lots * contract, plan.stop, plan.take_profit, ts, 0.0, idx, plan.confidence,
                                 list(plan.patterns), plan.risk_amount, plan.nominal_risk)
        log.warning("POSITION %s %.2f lot @ %.5f SL=%.5f TP=%.5f (ticket %s)", plan.side, lots, price, plan.stop, plan.take_profit, ticket)
        return self.position

    # --- sorties -----------------------------------------------------------------------------------------
    def _trade_from_deals(self, ts: Any, reason: str, idx: int) -> Trade:
        pos = self.position
        deals = list(self.mt5.history_deals_get(position=self._ticket) or ()) if self._ticket else []
        pnl = sum(getattr(d, "profit", 0.0) + getattr(d, "commission", 0.0) + getattr(d, "swap", 0.0) + getattr(d, "fee", 0.0) for d in deals)
        exit_price = float(deals[-1].price) if deals else pos.entry
        t = Trade(pos.side, pos.entry_time, ts, pos.entry, exit_price, pos.size, float(pnl), reason, pos.confidence, pos.patterns,
                  idx - pos.entry_idx, pos.risk_amount, pos.nominal_risk)
        self.trades.append(t)
        self.position, self._ticket = None, None
        return t

    def sync(self, ts: Any, idx: int = 0) -> Optional[Trade]:
        if self.position is None:
            return None
        still = any(int(p.ticket) == self._ticket for p in (self.mt5.positions_get(symbol=self.symbol) or ()))
        return None if still else self._trade_from_deals(ts, "server_exit", idx)

    def close_position(self, price: float, ts: Any, reason: str, idx: int = 0, market: bool = True) -> Trade:
        """Les clôtures restent permises même coupe-circuit actif (sortir est toujours plus sûr que rester)."""
        pos = self.position
        if pos is None:
            raise ExecutionError("Aucune position à fermer")
        m = self.mt5
        still = [p for p in (m.positions_get(symbol=self.symbol) or ()) if int(p.ticket) == self._ticket]
        if not still:
            return self._trade_from_deals(ts, reason, idx)
        iid = self.state.new_intent("CLOSE", pos.side, {"ticket": self._ticket, "reason": reason}, self.strategy)
        done, _transient, ambiguous = self._codes()
        tick = m.symbol_info_tick(self.symbol)
        long = pos.side == "long"
        req = {"action": m.TRADE_ACTION_DEAL, "symbol": self.symbol, "position": self._ticket, "volume": float(still[0].volume),
               "type": m.ORDER_TYPE_SELL if long else m.ORDER_TYPE_BUY, "price": float(tick.bid if long else tick.ask),
               "deviation": self.cfg.mt5_deviation_points, "magic": self.cfg.mt5_magic, "comment": f"qb:{iid}",
               "type_time": m.ORDER_TIME_GTC, "type_filling": self._filling()}
        chk = m.order_check(req)
        if chk is None or chk.retcode not in (0, done):
            self.state.mark(iid, "REFUSED", f"order_check: {getattr(chk, 'retcode', None)}")
            raise ExecutionError(f"Clôture refusée par order_check : {getattr(chk, 'retcode', None)}")
        self.state.mark(iid, "SENT")
        res = m.order_send(req)
        if res is None or res.retcode in ambiguous:
            self._ambiguous(iid, "réponse ambiguë à la clôture")
            if not any(int(p.ticket) == self._ticket for p in (m.positions_get(symbol=self.symbol) or ())):
                self.state.mark(iid, "CONFIRMED", "clôture constatée par réconciliation")
                return self._trade_from_deals(ts, reason, idx)
            raise ExecutionError("État INCONNU à la clôture ; coupe-circuit actif")
        if res.retcode != done:
            self.state.mark(iid, "REFUSED", f"retcode {res.retcode}")
            raise ExecutionError(f"Clôture refusée : {res.retcode}")
        self.state.mark(iid, "CONFIRMED", reason)
        return self._trade_from_deals(ts, reason, idx)

    # --- reprise -------------------------------------------------------------------------------------------
    def restore(self, engine_n: int) -> Optional[Position]:
        """Au démarrage : adopte une position portant notre magic ET connue de l'état ; toute autre = orpheline => coupe-circuit."""
        ours = [p for p in (self.mt5.positions_get(symbol=self.symbol) or ()) if p.magic == self.cfg.mt5_magic]
        if not ours:
            return None
        known = self.state.known_tickets()
        orphans = [p for p in ours if int(p.ticket) not in known]
        if orphans or len(ours) > 1:
            self.kill.trigger(f"position(s) orpheline(s) ou multiples au démarrage : {[int(p.ticket) for p in ours]}")
            raise ExecutionError("Position orpheline/multiple : coupe-circuit déclenché, intervention humaine requise")
        p = ours[0]
        contract = self.mt5.symbol_info(self.symbol).trade_contract_size
        self._ticket = int(p.ticket)
        side = "long" if p.type == self.mt5.POSITION_TYPE_BUY else "short"
        self.position = Position(side, float(p.price_open), float(p.volume) * contract, float(p.sl), float(p.tp), None, 0.0, engine_n, 0.0, [], 0.0, 0.0)
        self.state.log("WARNING", "restore", f"position {self._ticket} adoptée (la durée de détention repart de zéro)")
        return self.position
```
### quantbot/live/approvals.py
```python
"""Approbation HUMAINE : le programme ne l'écrit jamais. Sans approbation valide, le bot reste en OBSERVATION (aucun ordre).

Format de `approved_strategies.json` (à rédiger à la main) :
{"approved": [{"id": "amd", "instrument": "XAUUSD", "spec": "specs/inst_strategies_v1.json",
               "spec_sha256": "<empreinte du fichier de spec>", "approved_by": "nom", "date": "2026-10-26"}]}
L'empreinte lie l'approbation à la spec EXACTE : modifier la spec invalide l'approbation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_approval(strategy_id: str, instrument: str, spec_path: str | Path, approvals_path: str | Path) -> tuple[bool, str]:
    ap = Path(approvals_path)
    if not ap.exists():
        return False, "fichier d'approbation absent : mode observation"
    try:
        data = json.loads(ap.read_text(encoding="utf-8"))
        entries = data["approved"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return False, "fichier d'approbation illisible : mode observation"
    for e in entries:
        if e.get("id") == strategy_id and e.get("instrument") == instrument:
            if not e.get("approved_by") or not e.get("date"):
                return False, "approbation sans signataire/date : refusée"
            if not Path(spec_path).exists():
                return False, "spec introuvable : refusée"
            if e.get("spec_sha256") != file_sha256(spec_path):
                return False, "empreinte de spec différente : la spec a changé depuis l'approbation"
            return True, f"approuvée par {e['approved_by']} le {e['date']}"
    return False, f"stratégie {strategy_id}/{instrument} non approuvée : mode observation"
```
### quantbot/live/strategies.py
```python
"""Stratégies exécutables en direct : mêmes générateurs causaux que la recherche, appliqués sur la fenêtre récente."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from ..config import Settings
from ..data.mt5 import costs_from_frame
from ..lab.specs import build_settings
from ..strategies import amd, fvg, orb, vwap
from ..strategies.events import EventSignalEngine

HISTORY_BARS = 3000  # fenêtre : couvre l'expiration des zones FVG H4 (50 barres H4 ~ 800 barres M15) avec marge


def generate(strategy_id: str, scfg: dict, df: pd.DataFrame):
    if strategy_id == "amd":
        return amd.events(df, {**amd.PARAMS, **{k: tuple(v) if isinstance(v, list) else v for k, v in scfg["params"].items()}})
    if strategy_id == "vwap":
        return vwap.events(df, scfg["params"])
    if strategy_id == "orb":
        return orb.events(df, scfg["params"])
    if strategy_id in ("fvg_h1", "fvg_h4"):
        return fvg.events(df, scfg["rule"], scfg["params"])
    raise KeyError(f"stratégie inconnue : {strategy_id}")


class LiveEventSignalEngine:
    """Recalcule les événements sur la fenêtre et ne retient que celui de la DERNIÈRE barre (causalité => identique au backtest)."""

    def __init__(self, settings: Settings, strategy_id: str, scfg: dict) -> None:
        self.settings, self.strategy_id, self.scfg = settings, strategy_id, scfg

    def evaluate(self, window: pd.DataFrame, htf: Optional[pd.DataFrame] = None):
        last = window.index[-1]
        evs = [e for e in generate(self.strategy_id, self.scfg, window) if e.ts == last]
        return EventSignalEngine(self.settings, evs[:1]).evaluate(window) if evs else None


def load_spec(spec_path: str | Path) -> dict:
    return json.loads(Path(spec_path).read_text(encoding="utf-8"))


def strategy_settings(spec: dict, strategy_id: str, instrument: str, history: pd.DataFrame) -> Settings:
    scfg = spec["strategies"][strategy_id]
    if instrument not in scfg["instruments"]:
        raise KeyError(f"{strategy_id} n'est pas préenregistrée pour {instrument}")
    s = build_settings(spec, instrument, costs_from_frame(history), history)
    return s.with_overrides({"backtest.max_hold_bars": scfg["max_hold_bars"], "backtest.window_bars": HISTORY_BARS,
                             "execution.mt5_symbol": instrument})


def build_engine(spec: dict, strategy_id: str, settings: Settings) -> LiveEventSignalEngine:
    return LiveEventSignalEngine(settings, strategy_id, spec["strategies"][strategy_id])
```
### quantbot/live/runner.py
```python
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
                 allowed_servers: tuple = (), clock=time.time, sleep=time.sleep) -> None:
        self.mt5, self.symbol, self.strategy_id = mt5, symbol, strategy_id
        self.spec_path, self.approvals_path = Path(spec_path), Path(approvals_path)
        self.state = StateStore(state_path)
        self.kill = KillSwitch(self.state, kill_file)
        self.feed = BarFeed(mt5, symbol, timeframe, HISTORY_BARS, clock=clock)
        self.allowed_servers, self.clock, self.sleep = allowed_servers, clock, sleep
        self.engine: Optional[TradingEngine] = None
        self.mode = "NON_DEMARRE"
        self.steps = 0

    # --- démarrage --------------------------------------------------------------------------
    def setup(self) -> str:
        spec = load_spec(self.spec_path)
        df = self.feed._fetch()  # historique de démarrage (barres clôturées) pour régler coûts/levier
        df["spread"] = df["spread_points"] * float(getattr(self.mt5.symbol_info(self.symbol), "point", 0.0))
        settings: Settings = strategy_settings(spec, self.strategy_id, self.symbol, df)
        sig = build_engine(spec, self.strategy_id, settings)
        approved, why = check_approval(self.strategy_id, self.symbol, self.spec_path, self.approvals_path)
        blocked = self.kill.reasons()
        if approved and not blocked:
            self.mode = "DEMO_ACTIF"
            broker = HardenedMT5Broker(settings.execution, settings.ftmo, self.mt5, self.state, self.kill, self.strategy_id, self.allowed_servers)
        else:
            self.mode = "OBSERVATION"
            why = why if not approved else f"coupe-circuit actif au démarrage : {blocked}"
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
        self.state.set("mode", self.mode); self.state.set("why", why); self.state.set("strategy", self.strategy_id)
        self.state.log("INFO", "demarrage", f"mode={self.mode} ; {why}")
        return self.mode

    def _on_close(self, trade, ts) -> None:
        self.state.log("INFO", "trade", json.dumps({"side": trade.side, "reason": trade.reason, "pnl": round(trade.pnl, 2),
                                                    "r": round(trade.r_nominal, 3), "t": str(ts)}))

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
### quantbot/ui/server.py
```python
"""Interface locale (127.0.0.1 uniquement) : état du projet, résultats, calibration, données, rejeu d'un backtest.

Lecture seule sur les rapports. Le rejeu n'utilise QUE la période de recherche (la période verrouillée n'est jamais lue)
et n'envoie aucun ordre : le trading réel est verrouillé.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).parent / "index.html"
SPEC_ORDER = ["baseline_v0", "baseline_v1", "v2_calibrated"]
_cache: dict = {}
_lock = threading.Lock()


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def collect_state(root: Path = ROOT) -> dict:
    from ..lab.registry import TrialRegistry
    reports = root / "reports"
    reg_path = reports / "registry.jsonl"
    try:
        reg = TrialRegistry(reg_path) if reg_path.exists() else TrialRegistry()
        reg_ok, n_trials, locked = reg.verify(), reg.n_trials(), reg.locked_reads()
    except Exception:  # registre altéré
        reg_ok, n_trials, locked = False, 0, 0
    specs = []
    for name in SPEC_ORDER:
        spec = _read_json(root / "specs" / f"{name}.json")
        if spec is None:
            continue
        results = []
        for inst in spec.get("instruments", {}):
            r = _read_json(reports / name / f"{inst}.json")
            if r is None:
                results.append({"instrument": inst, "status": "non exécuté"})
                continue
            ev = r["evaluation"]
            m = ev["metrics"]
            results.append({"instrument": inst, "verdict": ev["verdict"], "n_trades": m["n_trades"],
                            "expectancy_R": m["expectancy_R"], "profit_factor": m["profit_factor"],
                            "worst_trade_R": m.get("worst_trade_R"), "years": m.get("years"),
                            "gates": ev["gates"], "reason": ev["reason"], "n_trials": ev["n_trials"],
                            "diagnostics": r.get("diagnostics"), "costs": r.get("costs_used")})
        specs.append({"name": name, "parent": spec.get("parent"), "hypothesis": spec.get("hypothesis"),
                      "change_reason": spec.get("change_reason"), "results": results})
    battery = _read_json(reports / "battery_v1" / "summary.json")
    prov = _read_json(root / "data" / "real" / "PROVENANCE.json") or {}
    verdicts = [r.get("verdict") for s in specs for r in s["results"]]
    return {
        "status": {"live_trading": "VERROUILLÉ (aucun ordre ne peut partir)", "edge_validated": any(v == "PASS" for v in verdicts),
                   "mt5_broker": "écrit, testé uniquement contre un faux terminal", "registry_chain_ok": reg_ok,
                   "trials": n_trials, "trials_budget": 30, "locked_reads": locked, "tests": "voir README"},
        "specs": specs,
        "battery": battery,
        "data": [{k: i.get(k) for k in ("symbol", "rows", "start", "end", "span_years", "sha256")} for i in prov.get("instruments", [])],
        "data_notes": ["Horloge courtier : UTC+2 hiver / UTC+3 été, calendrier européen (reconstruite depuis time_broker_epoch).",
                       "Export plafonné à 80 000 barres par instrument : ce n'est pas tout l'historique.",
                       "Spread EURUSD inutilisable (44-83 % de zéros) : hypothèse déclarée dans la spec.",
                       "USTEC : trou réel de 55 jours (16 juil. -> 9 sept. 2025), géré (positions clôturées, ré-échauffement)."],
    }


def run_replay(df: pd.DataFrame, settings, max_points: int = 500) -> dict:
    from ..backtest.engine import Backtester
    res = Backtester(settings).run(df)
    eq = res.equity_curve
    step = max(1, len(eq) // max_points)
    eq = eq.iloc[::step]
    trades = res.trades
    return {"metrics": {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in res.metrics.items()},
            "n_signals": res.n_signals, "rejections": res.rejections,
            "equity": [[str(t), float(v)] for t, v in zip(eq.index, eq.to_numpy())],
            "reasons": {k: sum(1 for t in trades if t.reason == k) for k in sorted({t.reason for t in trades})},
            "trades": [{"t": str(t.entry_time), "side": t.side, "reason": t.reason, "r_nominal": round(t.r_nominal, 3)}
                       for t in trades[-40:]]}


def replay_instrument(instrument: str, bars: int, spec_name: str = "baseline_v1", root: Path = ROOT) -> dict:
    from ..data.mt5 import costs_from_frame, load_mt5_csv
    from ..lab.locked import split_locked
    from ..lab.specs import build_settings
    spec = _read_json(root / "specs" / f"{spec_name}.json")
    if spec is None or instrument not in spec["instruments"]:
        raise ValueError("instrument ou spec inconnu")
    bars = max(500, min(int(bars), 20000))
    key = (instrument, bars, spec_name)
    with _lock:
        if key in _cache:
            return _cache[key]
    df = load_mt5_csv(root / "data" / "real" / spec["instruments"][instrument])
    research, _locked = split_locked(df, spec["lock_months"], spec["lock_min_frac"])  # la période verrouillée n'est jamais renvoyée
    seg = research.iloc[-bars:]
    settings = build_settings(spec, instrument, costs_from_frame(df), research)
    out = run_replay(seg, settings)
    ref = _read_json(root / "reports" / spec_name / f"{instrument}.json")
    ev = (ref or {}).get("evaluation")
    out["reference"] = None if ev is None else {"verdict": ev["verdict"], "n_trades": ev["metrics"]["n_trades"],
                                                "expectancy_R": ev["metrics"]["expectancy_R"], "profit_factor": ev["metrics"]["profit_factor"],
                                                "years": ev["metrics"].get("years")}
    out["buy_hold_return"] = float(seg["close"].iloc[-1] / seg["close"].iloc[0] - 1.0)
    out.update({"instrument": instrument, "spec": spec_name, "bars": len(seg), "start": str(seg.index[0]),
                "end": str(seg.index[-1]), "note": "Rejeu sur la période de RECHERCHE uniquement. Aucun ordre n'est envoyé."})
    with _lock:
        _cache[key] = out
    return out


class Handler(BaseHTTPRequestHandler):
    root = ROOT

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, default=str, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                self._send(200, STATIC.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/state":
                self._json(collect_state(self.root))
            elif url.path == "/api/replay":
                q = parse_qs(url.query)
                self._json(replay_instrument(q.get("instrument", [""])[0], int(q.get("bars", ["6000"])[0]),
                                             q.get("spec", ["baseline_v1"])[0], self.root))
            else:
                self._json({"error": "introuvable"}, 404)
        except (ValueError, KeyError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:  # pas de trace brute côté navigateur
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def log_message(self, *a) -> None:  # silence
        pass


def serve(port: int = 8790, root: Path = ROOT) -> None:
    Handler.root = root
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # JAMAIS 0.0.0.0
    print(f"quantbot UI : http://127.0.0.1:{port}/  (Ctrl+C pour arrêter)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
```
### tests/fake_mt5_live.py  (DOUBLE DE TEST — ne jamais l'utiliser hors des tests)
```python
"""Faux terminal MetaTrader 5 pour tester le bot en direct SANS terminal. Comportements scriptables : refus, requote, timeout (None)."""
from types import SimpleNamespace as NS

import numpy as np


class FakeMT5Live:
    TIMEFRAME_M1, TIMEFRAME_M15, TIMEFRAME_H1 = 1, 15, 16385
    TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TIME_GTC = 1, 0, 1, 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2
    TRADE_RETCODE_DONE, TRADE_RETCODE_REQUOTE, TRADE_RETCODE_PRICE_CHANGED = 10009, 10004, 10020
    TRADE_RETCODE_TIMEOUT, TRADE_RETCODE_REJECT, TRADE_RETCODE_NO_MONEY, TRADE_RETCODE_CONNECTION = 10012, 10006, 10019, 10031
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST, ACCOUNT_TRADE_MODE_REAL = 0, 1, 2
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1

    def __init__(self, n_bars=400, demo=True, login=1234, server="MetaQuotes-Demo", filling_mode=2, seed=0, price0=2000.0,
                 volume_min=0.01, trade_stops_level=0):
        rng = np.random.default_rng(seed)
        import calendar
        # la barre d'indice n_bars tombe un MARDI 11 h UTC (horloge courtier +3 h) : hors fenêtre de week-end
        self.t0 = calendar.timegm((2024, 6, 11, 14, 0, 0)) - 900 * n_bars
        px = price0 + np.cumsum(rng.normal(0, 0.4, n_bars + 1))
        self.bars = []
        for i in range(n_bars + 1):  # le DERNIER élément est la barre en formation
            o = px[i - 1] if i else price0
            c = px[i]
            self.bars.append({"time": self.t0 + 900 * i, "open": float(o), "high": float(max(o, c) + .2), "low": float(min(o, c) - .2),
                              "close": float(c), "tick_volume": 100 + i, "spread": 12, "real_volume": 0})
        self.acct = NS(login=login, currency="USD", server=server, balance=100_000.0, equity=100_000.0,
                       trade_mode=self.ACCOUNT_TRADE_MODE_DEMO if demo else self.ACCOUNT_TRADE_MODE_REAL)
        self.info = NS(currency_profit="USD", trade_contract_size=100, volume_step=0.01, volume_min=volume_min, volume_max=50.0,
                       filling_mode=filling_mode, digits=2, point=0.01, trade_stops_level=trade_stops_level)
        self.checked, self.sent, self.positions, self.deals = [], [], [], []
        self.check_script, self.send_script = [], []   # retcodes (int), "NONE" (réponse None), ou callable(req)
        self._ticket = 1000
        self.initialized = False

    # --- cycle de vie
    def initialize(self): self.initialized = True; return True
    def shutdown(self): self.initialized = False
    def last_error(self): return (1, "fake")
    def account_info(self): return self.acct
    def symbol_info(self, s): return self.info
    def symbol_select(self, s, e): return True

    def symbol_info_tick(self, s):
        c = self.bars[-1]["close"]
        return NS(bid=c, ask=c + 0.12)

    def advance(self, k=1):
        """k nouvelles barres : l'ancienne barre en formation devient close."""
        for _ in range(k):
            last = self.bars[-1]
            c = last["close"] + (0.3 if len(self.bars) % 2 else -0.2)
            self.bars.append({"time": last["time"] + 900, "open": last["close"], "high": max(last["close"], c) + .2,
                              "low": min(last["close"], c) - .2, "close": c, "tick_volume": last["tick_volume"] + 1, "spread": 12, "real_volume": 0})

    def copy_rates_from_pos(self, sym, tf, start, n):
        end = len(self.bars) - start
        return list(self.bars[max(0, end - n):end])

    # --- ordres
    def positions_get(self, symbol=None): return list(self.positions)
    def history_deals_get(self, position=None): return [d for d in self.deals if d.position_id == position]

    def order_check(self, req):
        self.checked.append(dict(req))
        r = self.check_script.pop(0) if self.check_script else 0
        if r == "NONE":
            return None
        return NS(retcode=r, comment="check")

    def order_send(self, req):
        self.sent.append(dict(req))
        b = self.send_script.pop(0) if self.send_script else self.TRADE_RETCODE_DONE
        if callable(b):
            return b(req)
        if b == "NONE":
            return None
        if b == "EXECUTED_BUT_NO_ANSWER":  # le serveur a exécuté mais la réponse est perdue
            self._execute(req)
            return None
        if b == self.TRADE_RETCODE_DONE:
            ticket = self._execute(req)
            return NS(retcode=b, comment="done", price=req["price"], order=ticket, deal=ticket + 1)
        return NS(retcode=b, comment="refus", price=0.0, order=0, deal=0)

    def _execute(self, req):
        if "position" in req:
            pos = next(p for p in self.positions if p.ticket == req["position"])
            self.positions = [p for p in self.positions if p.ticket != req["position"]]
            long = pos.type == self.POSITION_TYPE_BUY
            pnl = ((req["price"] - pos.price_open) if long else (pos.price_open - req["price"])) * pos.volume * self.info.trade_contract_size
            self.deals.append(NS(position_id=pos.ticket, profit=pnl, commission=-1.0, swap=0.0, fee=0.0, price=req["price"]))
            return pos.ticket
        self._ticket += 2
        self.positions.append(NS(ticket=self._ticket, magic=req["magic"], symbol=req["symbol"], volume=req["volume"],
                                 type=self.POSITION_TYPE_BUY if req["type"] == self.ORDER_TYPE_BUY else self.POSITION_TYPE_SELL,
                                 price_open=req["price"], sl=req["sl"], tp=req["tp"], comment=req.get("comment", "")))
        return self._ticket

    def server_side_exit(self, price):
        """SL/TP déclenché par le serveur."""
        for p in list(self.positions):
            self._execute({"position": p.ticket, "price": price})
```
