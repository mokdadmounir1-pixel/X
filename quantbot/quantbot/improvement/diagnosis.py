"""Analyse d'erreurs (OBSERVE / DIAGNOSE) et hypothèses d'amélioration (HYPOTHESIZE).

Les hypothèses ne sont QUE des surcharges de paramètres bornées par PARAM_SPACE :
ni les règles de l'utilisateur ni une IA ne peuvent injecter du code exécutable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..config import Settings
from ..execution.broker import Trade
from ..indicators.core import atr

# clé -> (min, max, pas) ou liste de valeurs permises
PARAM_SPACE: dict[str, Any] = {
    "tolerance.min_score": (0.50, 0.85, 0.05),
    "tolerance.tolerance_percentage": (0.08, 0.25, 0.01),
    "tolerance.deviation_threshold": (0.25, 0.50, 0.05),
    "signals.min_confidence": (0.40, 0.85, 0.05),
    "signals.min_edge": (0.0, 0.30, 0.05),
    "signals.require_confirmation": [False, True],
    "signals.trend_filter": ["none", "ema"],
    "detection.max_pivot_age": (4, 20, 2),
    "risk.atr_stop_mult": (0.5, 3.0, 0.5),
    "risk.reward_risk": (1.0, 5.0, 0.5),
    "risk.max_trades_per_day": (1, 10, 1),
}
MAX_CHANGES = 3


@dataclass
class Failure:
    kind: str
    severity: float  # 0..1
    evidence: dict = field(default_factory=dict)


@dataclass
class Hypothesis:
    description: str
    overrides: dict[str, Any]
    source: str = "rules"


def sanitize_overrides(raw: Any) -> dict[str, Any]:
    """Filtre une proposition (IA ou règles) : clés autorisées, valeurs bornées/arrondies."""
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, Any] = {}
    for key, value in raw.items():
        spec = PARAM_SPACE.get(key)
        if spec is None or len(clean) >= MAX_CHANGES:
            continue
        if isinstance(spec, list):
            if value in spec:
                clean[key] = value
            continue
        lo, hi, step = spec
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
            continue
        v = min(hi, max(lo, value))
        v = round(round((v - lo) / step) * step + lo, 6)
        clean[key] = int(v) if isinstance(lo, int) and isinstance(step, int) else v
    return clean


def analyze_failures(trades: list[Trade], df: pd.DataFrame, settings: Settings,
                     metrics: dict, rejections: Optional[dict] = None) -> list[Failure]:
    out: list[Failure] = []
    n = len(trades)
    if n == 0:
        out.append(Failure("no_trades", 1.0, {"rejections": rejections or {}}))
        return out
    if metrics["profit_factor"] < 1.0 or metrics["total_return"] < 0:
        out.append(Failure("underperforms", min(1.0, 1.0 - metrics["profit_factor"] + 0.3),
                           {"profit_factor": metrics["profit_factor"], "return": metrics["total_return"]}))
    if metrics["max_drawdown"] > settings.validation.max_drawdown * 0.7:
        out.append(Failure("high_drawdown", min(1.0, metrics["max_drawdown"] / settings.validation.max_drawdown),
                           {"max_drawdown": metrics["max_drawdown"]}))
    stops = sum(t.reason in ("stop_loss", "stop_gap") for t in trades) / n
    if stops > 0.65:
        out.append(Failure("stops_getting_hit", stops, {"stop_ratio": round(stops, 3)}))
    days = max(1, (pd.Timestamp(trades[-1].exit_time) - pd.Timestamp(trades[0].entry_time)).days)
    if n / days > settings.risk.max_trades_per_day * 0.8:
        out.append(Failure("excessive_trades", 0.6, {"trades_per_day": round(n / days, 2)}))
    gross = sum(abs(t.entry * t.size) for t in trades)
    if gross > 0:
        cost_drag = (settings.execution.fee_rate * 2 + settings.execution.slippage * 2) * gross
        net = sum(t.pnl for t in trades)
        if net < 0 < cost_drag and cost_drag > abs(net) * 0.5:
            out.append(Failure("cost_slippage_drag", 0.7, {"cost_drag": round(cost_drag, 2), "net": round(net, 2)}))
    regime = _volatility_regime_split(trades, df, settings.detection.atr_period)
    if regime:
        out.append(regime)
    return out


def _volatility_regime_split(trades: list[Trade], df: pd.DataFrame, period: int) -> Optional[Failure]:
    if len(trades) < 12:
        return None
    a = atr(df, period) / df["close"]
    vol = []
    for t in trades:
        loc = a.index.get_indexer([pd.Timestamp(t.entry_time)], method="pad")[0]
        vol.append(a.iloc[loc] if loc >= 0 else np.nan)
    vol = np.array(vol, dtype=float)
    ok = np.isfinite(vol)
    if ok.sum() < 12:
        return None
    pnl = np.array([t.pnl for t in trades])[ok]
    vol = vol[ok]
    cut = np.quantile(vol, 2 / 3)
    hi, lo = pnl[vol >= cut], pnl[vol < cut]
    if hi.size >= 4 and hi.sum() < 0 and hi.mean() < lo.mean():
        return Failure("high_volatility_regime", 0.7,
                       {"pnl_high_vol": round(float(hi.sum()), 2), "pnl_other": round(float(lo.sum()), 2)})
    return None


def propose_changes(failures: list[Failure], settings: Settings) -> list[Hypothesis]:
    """Hypothèses déterministes (repli sans IA)."""
    s = settings
    hyps: list[Hypothesis] = []
    kinds = {f.kind for f in failures}
    if "underperforms" in kinds or "no_trades" not in kinds:
        hyps.append(Hypothesis("Exiger des patterns plus proches du modèle (score min +0.05)",
                               {"tolerance.min_score": s.tolerance.min_score + 0.05}))
        hyps.append(Hypothesis("Exiger une confirmation (cassure) avant d'entrer",
                               {"signals.require_confirmation": True}))
    if "stops_getting_hit" in kinds:
        hyps.append(Hypothesis("Stops plus larges (ATR x +0.5)", {"risk.atr_stop_mult": s.risk.atr_stop_mult + 0.5}))
    if "high_volatility_regime" in kinds or "high_drawdown" in kinds:
        hyps.append(Hypothesis("Filtre de tendance EMA + confiance min +0.05",
                               {"signals.trend_filter": "ema", "signals.min_confidence": s.signals.min_confidence + 0.05}))
    if "excessive_trades" in kinds or "cost_slippage_drag" in kinds:
        hyps.append(Hypothesis("Moins de trades : écart min entre signaux +0.05, max 3/jour",
                               {"signals.min_edge": s.signals.min_edge + 0.05, "risk.max_trades_per_day": 3}))
    if "no_trades" in kinds:
        hyps.append(Hypothesis("Assouplir la détection : score min -0.05, tolérance +0.02",
                               {"tolerance.min_score": s.tolerance.min_score - 0.05,
                                "tolerance.tolerance_percentage": s.tolerance.tolerance_percentage + 0.02}))
    out = []
    for h in hyps:
        clean = sanitize_overrides(h.overrides)
        if clean and clean != {k: _current(s, k) for k in clean}:
            out.append(Hypothesis(h.description, clean, h.source))
    return out


def _current(s: Settings, dotted: str):
    section, _, key = dotted.partition(".")
    return getattr(getattr(s, section), key)
