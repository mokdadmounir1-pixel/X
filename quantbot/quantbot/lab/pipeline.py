"""Évaluation d'une spécification : recherche (répétable) puis période verrouillée (une seule fois)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..backtest.engine import Backtester
from ..config import Settings
from . import stats as st
from .gates import Gate, GateCfg, run_gates, verdict
from .locked import LockedSlice, final_evaluation
from .registry import TrialRegistry, canonical_hash

_SPEC_EXCLUDE = ("logging", "ai", "validation")


def spec_hash(settings: Settings, gate_cfg: GateCfg = GateCfg(), extra: Any = None) -> str:
    """Identifie la stratégie ET les seuils qui la jugent (changer un seuil change l'identité).

    `extra` (ex. hachage d'un modèle calibré) entre dans l'identité ; absent, le hachage reste celui des specs v0/v1.
    """
    d = {k: v for k, v in settings.to_dict().items() if k not in _SPEC_EXCLUDE}
    body = {"spec": d, "gates": gate_cfg.to_dict()}
    if extra is not None:
        body["extra"] = extra
    return canonical_hash(body)


def data_hash(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update(df[["open", "high", "low", "close"]].to_numpy(dtype="float64").tobytes())
    h.update(df.index.values.astype("datetime64[ns]").astype("int64").tobytes())  # indépendant de la résolution
    return h.hexdigest()


@dataclass
class Evaluation:
    verdict: str
    reason: str
    gates: list[Gate]
    metrics: dict
    n_trials: int
    spec_hash: str
    data_hash: str

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "reason": self.reason, "n_trials": self.n_trials,
                "spec_hash": self.spec_hash, "data_hash": self.data_hash, "metrics": self.metrics,
                "gates": [g.to_dict() for g in self.gates]}


def _fold_expectancies(df: pd.DataFrame, settings: Settings, k: int, signal_engine: Any) -> list[float]:
    warm = settings.backtest.warmup_bars
    usable = len(df) - warm
    if usable < k * 40:
        return []
    edges = [warm + round(usable * j / k) for j in range(k + 1)]
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        seg = df.iloc[max(0, a - warm): b]
        if len(seg) < warm + 20:
            out.append(0.0)
            continue
        res = Backtester(settings, 1.0, signal_engine).run(seg)
        r = [t.r_nominal for t in res.trades]
        out.append(st.expectancy(r) if len(r) >= 10 else 0.0)
    return out


def evaluate_research(df_research: pd.DataFrame, settings: Settings, registry: TrialRegistry,
                      gate_cfg: GateCfg = GateCfg(), signal_engine: Any = None, spec_extra: Any = None) -> Evaluation:
    """Évalue la spec sur les données de RECHERCHE. Aucune sélection de paramètres ici :
    la spec est supposée figée avant ce test (sinon l'essai doit être compté comme un essai de plus)."""
    sh, dh = spec_hash(settings, gate_cfg, spec_extra), data_hash(df_research)
    base = Backtester(settings, 1.0, signal_engine).run(df_research)
    costly = Backtester(settings, settings.validation.cost_stress_multiplier, signal_engine).run(df_research)
    r = np.array([t.r_nominal for t in base.trades])
    r2 = np.array([t.r_nominal for t in costly.trades])
    folds = _fold_expectancies(df_research, settings, settings.validation.walk_forward_windows, signal_engine)
    sr, _, _, n = st.sharpe_moments(r)
    registry.record_trial(sh, dh, sr, n)
    n_trials, var_sr = registry.n_trials(), registry.var_sharpe()
    years = max((df_research.index[-1] - df_research.index[0]).days / 365.25, 1e-9)
    gates = run_gates(r, r2, folds, n_trials, var_sr, years, settings.risk.risk_per_trade * 100,
                      settings.ftmo.max_total_loss * 100, gate_cfg)
    exp = st.expectancy(r)
    v, why = verdict(gates, exp, years, gate_cfg)
    metrics = {"n_trades": n, "expectancy_R": exp, "profit_factor": st.profit_factor(r), "years": years,
               "sharpe_per_trade": sr, "worst_trade_R": float(r.min()) if r.size else 0.0, "median_R": float(np.median(r)) if r.size else 0.0, "total_return": base.metrics["total_return"],
               "max_drawdown": base.metrics["max_drawdown"]}
    evaluation = Evaluation(v, why, gates, metrics, n_trials, sh, dh)
    registry.append("evaluation", {"spec_hash": sh, "data_hash": dh, "verdict": v, "reason": why})
    return evaluation


def evaluate_locked(locked: LockedSlice, settings: Settings, registry: TrialRegistry,
                    gate_cfg: GateCfg = GateCfg(), signal_engine: Any = None, min_trades: int = 30) -> dict:
    """Lecture UNIQUE de la période verrouillée : confirmation (espérance > 0 et PF > 1), pas une optimisation."""
    sh = spec_hash(settings, gate_cfg)

    def fn(full: pd.DataFrame, lock_start: pd.Timestamp) -> dict:
        warm = settings.backtest.warmup_bars
        i = full.index.searchsorted(lock_start)
        res = Backtester(settings, 1.0, signal_engine).run(full.iloc[max(0, i - warm):])
        r = np.array([t.r_nominal for t in res.trades if t.entry_time >= lock_start])
        ok = bool(r.size >= min_trades and st.expectancy(r) > 0 and st.profit_factor(r) > 1.0)
        return {"n_trades": int(r.size), "expectancy_R": st.expectancy(r), "profit_factor": st.profit_factor(r),
                "verdict": "CONFIRMED" if ok else "NOT_CONFIRMED"}

    return final_evaluation(locked, sh, registry, fn)
