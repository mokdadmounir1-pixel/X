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
class ActiveRiskConfig(_Section):
    """Contrôle ACTIF du risque (désactivé par défaut : les essais passés n'en dépendent pas). Voir risk/active.py."""
    enabled: bool = False
    daily_loss_halt: float = 0.015       # perte du jour (réalisée + latente) en fraction de l'equity de début de jour => plus aucune entrée aujourd'hui
    daily_loss_flatten: bool = True      # ... et clôture de la position ouverte
    dd_throttle_start: float = 0.02      # drawdown depuis le plus haut : au-delà, le risque par trade diminue linéairement
    max_drawdown_halt: float = 0.06      # drawdown à partir duquel le bot s'ARRÊTE (plus aucune entrée) pendant halt_cooldown_days
    halt_cooldown_days: int = 3
    drift_window: int = 20               # nombre de derniers trades pour juger la dérive
    drift_min_mean_r: float = -0.30      # espérance glissante < seuil => arrêt (dérive de performance)
    max_consecutive_losses: int = 6
    vol_ratio_halt: float = 3.0          # ATR% courant / médiane des 500 dernières barres >= seuil => arrêt tant que la volatilité reste anormale
    kelly_fraction: float = 0.25         # fraction de Kelly (borne inférieure de Wilson) ; ne dépasse JAMAIS le risque de base
    kelly_min_trades: int = 30
    min_risk_multiplier: float = 0.25

    def validate(self) -> None:
        _require(0 < self.daily_loss_halt <= 0.2 and 0 < self.max_drawdown_halt <= 0.5, "daily_loss_halt/max_drawdown_halt hors bornes")
        _require(0 <= self.dd_throttle_start < self.max_drawdown_halt, "dd_throttle_start < max_drawdown_halt")
        _require(self.halt_cooldown_days >= 0 and self.drift_window >= 5 and self.max_consecutive_losses >= 2, "paramètres de dérive invalides")
        _require(0 < self.kelly_fraction <= 1 and 0 < self.min_risk_multiplier <= 1 and self.vol_ratio_halt > 1, "kelly_fraction/min_risk_multiplier/vol_ratio_halt invalides")


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
    hermes_model: str = "hermes3"
    hermes_url: str = "http://127.0.0.1:11434"        # serveur local Ollama-compatible ; toute adresse non locale est refusée
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
    "active_risk": ActiveRiskConfig,
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
    active_risk: ActiveRiskConfig = field(default_factory=ActiveRiskConfig)
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
