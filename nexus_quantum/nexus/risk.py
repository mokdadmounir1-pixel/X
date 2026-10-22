"""Risk Guardian: controle pre-ordre non contournable (noyau, sans I/O).

Principes:
- toute decision passe par check(); aucune strategie n'a de chemin alternatif;
- les limites dures sont immuables; tighten() n'accepte que des durcissements;
- etat inconnu (non reconcilie) => nouvelles entrees bloquees (reductions OK);
- annulation/liquidation = DEMANDE, jamais "faite" avant confirmation broker;
- un HALT est verrouille: redemarrage seulement via authorize_restart().
Limite: ce noyau ne voit que ce qu'on lui rapporte; la fiabilite des entrees
(positions broker, equity, horodatages) est une hypothese a tester a l'integration.
"""
from __future__ import annotations

import dataclasses
import enum
from collections import deque
from dataclasses import dataclass


class Mode(enum.Enum):
    NORMAL = 0
    REDUCE_ONLY = 1   # entrees bloquees, reductions permises
    HALTED = 2        # tout rejete sauf ordres de liquidation valides


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    multiplier: float      # valeur monetaire d'1.0 de prix par contrat
    tick_size: float
    currency: str = "USD"


@dataclass(frozen=True)
class HardLimits:
    max_order_notional: float
    max_position_notional: float      # par symbole, apres execution
    max_gross_notional: float
    max_risk_per_trade: float         # perte si stop touche (hors gap)
    max_daily_loss: float             # positif
    max_drawdown: float               # positif, depuis le pic d'equity
    max_open_orders: int
    max_orders_per_minute: int
    max_data_age_s: float

    def tighten(self, **changes) -> "HardLimits":
        """Toutes les limites sont de type 'plus petit = plus strict'."""
        for k, v in changes.items():
            if not hasattr(self, k):
                raise ValueError(f"limite inconnue: {k}")
            if v > getattr(self, k):
                raise ValueError(f"{k}: assouplissement interdit "
                                 f"({getattr(self, k)} -> {v})")
            if v <= 0:
                raise ValueError(f"{k}: doit rester > 0")
        return dataclasses.replace(self, **changes)


@dataclass(frozen=True)
class Order:
    order_id: str
    strategy: str
    symbol: str
    side: int                 # +1 achat, -1 vente
    qty: float
    price: float
    stop_price: float | None = None
    liquidation: bool = False  # emis par la procedure d'urgence


@dataclass(frozen=True)
class Decision:
    approved: bool
    reasons: tuple[str, ...] = ()


@dataclass
class ActionRequest:
    kind: str                  # "CANCEL_ALL" | "LIQUIDATE"
    request_id: int
    status: str = "REQUESTED"  # REQUESTED -> CONFIRMED (jamais automatique)


class RiskGuardian:
    def __init__(self, limits: HardLimits, specs: dict[str, InstrumentSpec],
                 equity: float):
        self._limits = limits
        self._specs = dict(specs)
        self.mode = Mode.NORMAL
        self.halt_reason: str | None = None
        self.positions: dict[str, float] = {}
        self.reconciled = False          # etat inconnu au demarrage
        self.equity = equity
        self.sod_equity = equity
        self.peak_equity = equity
        self.last_tick: dict[str, float] = {}
        self.last_price: dict[str, float] = {}
        self.open_orders = 0
        self._seen: set[str] = set()
        self._recent: deque[float] = deque()
        self._reqs: list[ActionRequest] = []
        self.audit: list[tuple[str, str]] = []

    @property
    def limits(self) -> HardLimits:
        return self._limits

    def tighten(self, **changes) -> None:
        self._limits = self._limits.tighten(**changes)
        self._log("TIGHTEN", str(changes))

    def _log(self, ev: str, msg: str) -> None:
        self.audit.append((ev, msg))

    # ---- etats ----
    def halt(self, reason: str) -> None:
        self.mode = Mode.HALTED
        self.halt_reason = reason
        self._log("HALT", reason)

    def reduce_only(self, reason: str) -> None:
        if self.mode is Mode.NORMAL:
            self.mode = Mode.REDUCE_ONLY
        self._log("REDUCE_ONLY", reason)

    def _breach_active(self) -> bool:
        return (self.equity - self.sod_equity <= -self._limits.max_daily_loss
                or self.peak_equity - self.equity >= self._limits.max_drawdown)

    def authorize_restart(self, operator: str) -> bool:
        """Seul chemin de sortie de HALTED/REDUCE_ONLY. Exige etat reconcilie."""
        if not operator:
            return False
        if not self.reconciled:
            self._log("RESTART_REFUSED", f"{operator}: etat non reconcilie")
            return False
        if self._breach_active():
            self._log("RESTART_REFUSED", f"{operator}: limite toujours violee")
            return False
        self.mode, self.halt_reason = Mode.NORMAL, None
        self._log("RESTART", operator)
        return True

    def new_day(self, equity: float) -> None:
        self.sod_equity = equity

    def update_equity(self, equity: float) -> None:
        self.equity = equity
        self.peak_equity = max(self.peak_equity, equity)
        if equity - self.sod_equity <= -self._limits.max_daily_loss:
            self.halt("max_daily_loss")
        elif self.peak_equity - equity >= self._limits.max_drawdown:
            self.halt("max_drawdown")

    def on_tick(self, symbol: str, ts: float, price: float | None = None) -> None:
        self.last_tick[symbol] = ts
        if price is not None:
            self.last_price[symbol] = price

    # ---- reconciliation: la verite est le broker ----
    def reconcile(self, broker_positions: dict[str, float], tol: float = 1e-9) -> bool:
        """True si la vue interne concordait (ou alignement initial).

        Un ecart sur un etat precedemment reconcilie => REDUCE_ONLY + non reconcilie
        jusqu'a un nouveau passage; la sortie du mode exige authorize_restart().
        """
        broker = {s: q for s, q in broker_positions.items() if abs(q) > tol}
        diffs = {s: (self.positions.get(s, 0.0), broker.get(s, 0.0))
                 for s in set(broker) | set(self.positions)
                 if abs(self.positions.get(s, 0.0) - broker.get(s, 0.0)) > tol}
        was_reconciled = self.reconciled
        self.positions = broker
        if diffs and was_reconciled:
            self.reconciled = False
            self.reduce_only(f"ecart de position: {diffs}")
            return False
        self.reconciled = True
        self._log("RECONCILED", f"{len(broker)} positions (verite broker)")
        return not diffs

    # ---- demandes d'urgence ----
    def request_cancel_all(self) -> ActionRequest:
        r = ActionRequest("CANCEL_ALL", len(self._reqs))
        self._reqs.append(r)
        self.reduce_only("cancel_all demande")
        return r

    def request_liquidation(self) -> ActionRequest:
        r = ActionRequest("LIQUIDATE", len(self._reqs))
        self._reqs.append(r)
        self.halt("liquidation demandee")
        return r

    def confirm(self, req: ActionRequest, broker_open_orders: int,
                broker_positions: dict[str, float]) -> bool:
        """Confirme uniquement sur preuve independante du broker."""
        if req.kind == "CANCEL_ALL":
            ok = broker_open_orders == 0
        else:
            ok = all(abs(q) < 1e-12 for q in broker_positions.values())
        if ok:
            req.status = "CONFIRMED"
            self.open_orders = broker_open_orders
            if req.kind == "LIQUIDATE":
                self.positions = {}
        self._log("CONFIRM" if ok else "CONFIRM_FAILED", f"{req.kind}#{req.request_id}")
        return ok

    def liquidation_orders(self, prices: dict[str, float]) -> list[Order]:
        return [Order(f"LIQ-{s}-{len(self.audit)}", "RISK", s,
                      -1 if q > 0 else 1, abs(q), prices[s], liquidation=True)
                for s, q in self.positions.items() if q]

    # ---- coeur: verification pre-ordre ----
    def check(self, o: Order, now: float) -> Decision:
        L, R = self._limits, []
        spec = self._specs.get(o.symbol)
        if spec is None:
            return Decision(False, ("symbole_inconnu",))
        if o.side not in (1, -1) or o.qty <= 0 or o.price <= 0:
            return Decision(False, ("ordre_invalide",))
        if o.order_id in self._seen:
            return Decision(False, ("ordre_duplique",))

        pos = self.positions.get(o.symbol, 0.0)
        new_pos = pos + o.side * o.qty
        # reduction stricte: |position| diminue sans inversion de signe
        reducing = pos != 0 and abs(new_pos) < abs(pos) and pos * new_pos >= 0

        if self.mode is Mode.HALTED:
            if not (o.liquidation and reducing):
                return Decision(False, ("halted:" + str(self.halt_reason),))
        elif self.mode is Mode.REDUCE_ONLY and not reducing:
            return Decision(False, ("reduce_only",))

        if not reducing:                  # contraintes d'ENTREE
            if not self.reconciled:
                R.append("etat_non_reconcilie")
            if now - self.last_tick.get(o.symbol, float("-inf")) > L.max_data_age_s:
                R.append("donnees_perimees")
            if o.stop_price is None:
                R.append("stop_obligatoire")
            else:
                if (o.side == 1 and o.stop_price >= o.price) or \
                   (o.side == -1 and o.stop_price <= o.price):
                    R.append("stop_du_mauvais_cote")
                if o.qty * abs(o.price - o.stop_price) * spec.multiplier > L.max_risk_per_trade:
                    R.append("risque_par_trade")
            if self.open_orders >= L.max_open_orders:
                R.append("max_ordres_ouverts")
            while self._recent and now - self._recent[0] > 60:
                self._recent.popleft()
            if len(self._recent) >= L.max_orders_per_minute:
                R.append("cadence_ordres")
            if o.qty * o.price * spec.multiplier > L.max_order_notional:
                R.append("notionnel_ordre")
            if abs(new_pos) * o.price * spec.multiplier > L.max_position_notional:
                R.append("notionnel_position")
            gross = abs(new_pos) * o.price * spec.multiplier + sum(
                abs(q) * self.last_price.get(s, o.price) * self._specs[s].multiplier
                for s, q in self.positions.items() if s != o.symbol and s in self._specs)
            if gross > L.max_gross_notional:
                R.append("notionnel_brut")

        if R:
            return Decision(False, tuple(R))
        self._seen.add(o.order_id)
        self._recent.append(now)
        return Decision(True)

    def on_fill(self, symbol: str, signed_qty: float) -> None:
        """Les fills broker sont la verite; jamais deduits d'un ordre envoye."""
        q = self.positions.get(symbol, 0.0) + signed_qty
        if abs(q) < 1e-12:
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = q
