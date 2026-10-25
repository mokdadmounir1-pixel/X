"""Rejeu visuel d'une stratégie : chaque trade avec entrée, stop (SL), objectif (TP), sortie, motif et R, pour LIRE ce que fait le moteur.

Lecture seule : période de RECHERCHE uniquement (la période verrouillée n'est jamais renvoyée) ou segment ANTÉRIEUR (data/deep) ; aucun ordre.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_cache: dict = {}
_lock = threading.Lock()
MAX_TRADES = 1500


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def objective(root: Path) -> dict:
    o = _read(root / "specs" / "objective.json") or {}
    base = _read(root / "specs" / "inst_strategies_v1.json") or {}
    risk = ((base.get("settings") or {}).get("risk") or {}).get("risk_per_trade", 0.005)
    return {"target_r_per_day": float(o.get("target_r_per_day", 0.33)), "note": o.get("note", ""), "beta_flags": o.get("beta_flags", {}), "risk_per_trade": float(risk)}


def list_strategies(root: Path) -> dict:
    base = _read(root / "specs" / "inst_strategies_v1.json") or {}
    out = [{"id": n, "label": s["label"], "instruments": s["instruments"], "note": s.get("note", "")} for n, s in base.get("strategies", {}).items()]
    deep = {i: (root / "data" / "deep" / f).is_file() for i, f in (base.get("instruments") or {}).items()}
    return {"strategies": out, "patterns": {"id": "patterns", "label": "Figures floues (baseline_v1)", "instruments": list((base.get("instruments") or {}))},
            "deep_available": deep, "objective": objective(root)}


def daily_stats(trades: list, df: pd.DataFrame, target: float) -> dict:
    """R par JOUR OUVRÉ de la fenêtre (les jours sans trade comptent pour 0) : c'est l'unité de l'objectif."""
    if df.empty:
        return {}
    days = max(int(np.busday_count(df.index[0].date(), df.index[-1].date())) + 1, 1)
    by_day: dict = {}
    for t in trades:
        d = pd.Timestamp(t.exit_time).date()
        by_day[d] = by_day.get(d, 0.0) + float(t.r_nominal)
    total = float(sum(by_day.values()))
    series = [[str(d), round(v, 3)] for d, v in sorted(by_day.items())]
    return {"window_days": days, "total_R": round(total, 3), "avg_R_per_day": total / days, "target": target,
            "days_with_trade": len(by_day), "days_ge_target_pct": (sum(v >= target for v in by_day.values()) / days) if days else 0.0,
            "best_day_R": max(by_day.values()) if by_day else 0.0, "worst_day_R": min(by_day.values()) if by_day else 0.0, "series": series[-400:]}


def run_strategy_replay(instrument: str, bars: int, strategy: str, segment: str = "recherche", root: Path = Path(".")) -> dict:
    from ..backtest.engine import Backtester
    from ..data.mt5 import costs_from_frame, load_mt5_csv
    from ..lab.locked import split_locked
    from ..lab.specs import build_settings
    from ..strategies.build import events_for
    from ..strategies.events import EventSignalEngine
    from .server import run_replay as legacy_replay  # noqa: F401  (même moteur pour les figures floues)

    bars = max(500, min(int(bars), 12000))
    key = (instrument, bars, strategy, segment)
    with _lock:
        if key in _cache:
            return _cache[key]
    base = _read(root / "specs" / "inst_strategies_v1.json")
    if base is None or instrument not in base["instruments"]:
        raise ValueError("instrument inconnu")
    fname = base["instruments"][instrument]
    full = load_mt5_csv(root / "data" / "real" / fname)
    research, _locked = split_locked(full, base["lock_months"], base["lock_min_frac"])      # la période verrouillée n'est jamais renvoyée
    if segment == "avant":
        deep_path = root / "data" / "deep" / fname
        if not deep_path.is_file():
            raise ValueError("historique profond absent (data/deep) : lancer scripts/run_c8.py")
        deep = load_mt5_csv(deep_path)
        seg_all = deep[deep.index < full.index[0]]
        if len(seg_all) < 500:
            raise ValueError("pas assez de barres avant la période de recherche")
        seg, basis = seg_all.iloc[-bars:], seg_all
    elif segment == "recherche":
        seg, basis = research.iloc[-bars:], research
    else:
        raise ValueError("segment inconnu")
    measured = costs_from_frame(basis)
    if strategy == "patterns":
        spec = _read(root / "specs" / "baseline_v1.json")
        settings = build_settings(spec, instrument, measured, basis)
        eng, label = None, "Figures floues (baseline_v1)"
    else:
        scfg = base["strategies"].get(strategy)
        if scfg is None or instrument not in scfg["instruments"]:
            raise ValueError("stratégie inconnue pour cet instrument")
        settings = build_settings(base, instrument, measured, basis).with_overrides({"backtest.max_hold_bars": scfg["max_hold_bars"]})
        eng, label = EventSignalEngine(settings, events_for(strategy, scfg, seg)), scfg["label"]
    res = Backtester(settings, 1.0, eng).run(seg) if eng is not None else Backtester(settings).run(seg)
    trades = res.trades[-MAX_TRADES:]
    idx = seg.index
    t_epoch = (idx.astype("datetime64[ns]").astype("int64") // 10**9).tolist()
    e_idx = idx.get_indexer([pd.Timestamp(t.entry_time) for t in trades], method="pad").tolist()
    x_idx = idx.get_indexer([pd.Timestamp(t.exit_time) for t in trades], method="pad").tolist()
    r = np.array([t.r_nominal for t in res.trades], dtype=float)
    target = objective(root)["target_r_per_day"]
    daily = daily_stats(res.trades, seg, target)
    reasons = {}
    for t in res.trades:
        a = reasons.setdefault(t.reason, {"n": 0, "sumR": 0.0, "wins": 0})
        a["n"] += 1; a["sumR"] += float(t.r_nominal); a["wins"] += int(t.r_nominal > 0)
    eq = res.equity_curve
    step = max(1, len(eq) // 600)
    out = {
        "instrument": instrument, "strategy": strategy, "label": label, "segment": segment, "start": str(seg.index[0]), "end": str(seg.index[-1]), "n_bars": len(seg),
        "metrics": {"n_trades": int(len(r)), "expectancy_R": float(r.mean()) if len(r) else None,
                    "profit_factor": float(r[r > 0].sum() / -r[r < 0].sum()) if (r < 0).any() and (r > 0).any() else None,
                    "win_rate": float((r > 0).mean()) if len(r) else None, "worst_R": float(r.min()) if len(r) else None, "best_R": float(r.max()) if len(r) else None,
                    "max_drawdown": float(res.metrics.get("max_drawdown", 0.0)), "total_return": float(res.metrics.get("total_return", 0.0))},
        "daily": daily, "reasons": {k: {"n": v["n"], "mean_R": v["sumR"] / v["n"], "win_rate": v["wins"] / v["n"]} for k, v in sorted(reasons.items())},
        "bars": {"t": t_epoch, "o": [round(float(x), 5) for x in seg["open"]], "h": [round(float(x), 5) for x in seg["high"]],
                 "l": [round(float(x), 5) for x in seg["low"]], "c": [round(float(x), 5) for x in seg["close"]]},
        "trades": [{"i0": a, "i1": b, "side": t.side, "entry": float(t.entry), "exit": float(t.exit), "stop": float(t.stop) or None, "tp": float(t.take_profit) or None,
                    "r": round(float(t.r_nominal), 3), "reason": t.reason, "held": int(t.bars_held), "pnl": round(float(t.pnl), 2)}
                   for t, a, b in zip(trades, e_idx, x_idx)],
        "equity": [[str(t), float(v)] for t, v in zip(eq.index[::step], eq.to_numpy()[::step])],
        "buy_hold_return": float(seg["close"].iloc[-1] / seg["close"].iloc[0] - 1.0),
        "note": "Fenêtre courte : ce rejeu sert à LIRE les trades ; seules les évaluations des portes (onglet Résultats) et le futur comptent pour juger. Coûts et risque hérités de la spec.",
    }
    with _lock:
        _cache[key] = out
    return out
