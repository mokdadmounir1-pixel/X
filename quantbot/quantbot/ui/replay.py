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

from collections import OrderedDict
_cache: OrderedDict = OrderedDict()      # LRU borné : le nombre de barres demandé est libre, la mémoire ne doit pas croître sans limite
_CACHE_MAX = 48
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
    return {"target_r_per_day": float(o.get("target_r_per_day", 0.33)), "note": o.get("note", ""), "beta_flags": o.get("beta_flags", {}), "target_monthly_net": float(o.get("target_monthly_net", 0.02)), "risk_per_trade": float(risk)}


SPEC_FILES = ["inst_strategies_v1", "smc_v1b", "gold_quant_v1", "gold_winrate_v1b", "apex_pullback_v1", "stop_hunt_v2", "stop_hunt_v3", "apex_levels_v1", "mtf_confluence_v1"]      # specs préenregistrées dont les stratégies sont rejouables


def spec_for(strategy: str, root: Path) -> Optional[dict]:
    for name in SPEC_FILES:
        sp = _read(root / "specs" / f"{name}.json")
        if sp and strategy in sp.get("strategies", {}):
            return sp
    return None


TF_SUFFIX = "_M15.csv"


def available_instruments(root: Path) -> dict:
    """Tous les instruments pour lesquels un CSV M15 existe : exports de recherche (data/real), barres synchronisées (data/live), crypto Coinbase (data/crypto). {nom: {"path", "kind", "origin"}} ; la recherche prime."""
    out: dict = {}
    for origin, kind in (("crypto", "utc"), ("live", "mt5"), ("real", "mt5")):          # l'ordre fait que « real » écrase « live » qui écrase « crypto »
        d = Path(root) / "data" / origin
        for f in sorted(d.glob("*" + TF_SUFFIX)) if d.is_dir() else []:
            out[f.name[: -len(TF_SUFFIX)]] = {"path": f, "kind": kind, "origin": origin}
    return out


def load_prices(root: Path, instrument: str, fname: Optional[str] = None):
    from ..data.coinbase import load_utc_csv
    from ..data.mt5 import load_mt5_csv
    av = available_instruments(root)
    if instrument in av:
        a = av[instrument]
        return (load_utc_csv(a["path"]) if a["kind"] == "utc" else load_mt5_csv(a["path"])), a
    if fname:                                                    # instrument de spec dont le fichier n'est pas dans les dossiers standard
        return load_mt5_csv(_price_csv(root, fname)), {"origin": "spec", "kind": "mt5"}
    raise ValueError(f"aucune donnée M15 pour {instrument} : lancer le terminal (synchronisation) ou copier {instrument}{TF_SUFFIX} dans data/real")


def exploration_costs(base: dict, instrument: str, kind: str, root: Path) -> dict:
    """Coûts d'un instrument HORS spec préenregistrée : spread MESURÉ sur le CSV si fiable ; commission nulle et glissement 1e-5 = HYPOTHÈSES déclarées ; crypto : frais de crypto_paper_v1 (hypothèses). Jamais un coût nul supposé pour le spread."""
    if kind == "utc":
        c = ((_read(root / "specs" / "crypto_paper_v1.json") or {}).get("costs") or {}).get("BTC-USD")
        if c:
            return {**c, "basis": "HYPOTHÈSE crypto (frais de détail Coinbase) : exploration"}
        return {"spread_frac": 0.0003, "fee_rate": 0.004, "slippage": 0.0005, "basis": "HYPOTHÈSE crypto : exploration"}
    return {"spread_frac": None, "fee_rate": 0.0, "slippage": 1e-05, "basis": "spread mesuré, commission 0 = HYPOTHÈSE : exploration, à re-mesurer sur le compte"}


def list_strategies(root: Path) -> dict:
    base = _read(root / "specs" / "inst_strategies_v1.json") or {}
    out = []
    for name in SPEC_FILES:
        sp = _read(root / "specs" / f"{name}.json") or {}
        out += [{"id": n, "label": s["label"], "instruments": s["instruments"], "note": s.get("note", ""), "spec": name} for n, s in sp.get("strategies", {}).items()]
    deep = {i: (root / "data" / "deep" / f).is_file() for i, f in (base.get("instruments") or {}).items()}
    av = available_instruments(root)
    inst_all = sorted(set(av) | {i for s in out for i in s["instruments"]})
    return {"strategies": out, "patterns": {"id": "patterns", "label": "Figures floues (baseline_v1)", "instruments": list((base.get("instruments") or {}))},
            "deep_available": deep, "objective": objective(root), "instruments_all": [{"id": i, "origin": (av.get(i) or {}).get("origin", "spec"), "available": i in av} for i in inst_all],
            "exploration_note": "Un instrument hors de la spec préenregistrée d'une stratégie est rejoué en EXPLORATION : mêmes règles figées, coûts mesurés ou hypothèses déclarées, aucun essai compté, aucune validité statistique."}


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


def _price_csv(root: Path, fname: str) -> Path:
    """Exports de recherche (data/real) en priorité ; à défaut, barres synchronisées automatiquement par le terminal (data/live, même format)."""
    real = root / "data" / "real" / fname
    live = root / "data" / "live" / fname
    return real if real.is_file() or not live.is_file() else live


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
    base = spec_for(strategy, root) if strategy != "patterns" else _read(root / "specs" / "inst_strategies_v1.json")
    if base is None:
        raise ValueError("stratégie inconnue")
    scfg0 = None if strategy == "patterns" else base["strategies"].get(strategy)
    in_spec = instrument in base["instruments"] and (scfg0 is None or instrument in scfg0["instruments"])
    fname = base["instruments"].get(instrument) or f"{instrument}{TF_SUFFIX}"
    full, src = load_prices(root, instrument, fname if in_spec else None)
    exploration = not in_spec
    if exploration:                                              # coûts propres à l'instrument (spec copiée, jamais modifiée sur disque)
        base = {**base, "instruments": {**base["instruments"], instrument: fname}, "costs": {**base["costs"], instrument: exploration_costs(base, instrument, src["kind"], root)}}
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
        if exploration:
            raise ValueError("figures floues : instruments de la spec seulement (choisir une stratégie à règles pour explorer d'autres instruments)")
        spec = _read(root / "specs" / "baseline_v1.json")
        settings = build_settings(spec, instrument, measured, basis)
        eng, label = None, "Figures floues (baseline_v1)"
    else:
        scfg = base["strategies"].get(strategy)
        if scfg is None:
            raise ValueError("stratégie inconnue")
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
        "instrument": instrument, "strategy": strategy, "label": label, "segment": segment, "exploration": exploration, "data_origin": src.get("origin"), "start": str(seg.index[0]), "end": str(seg.index[-1]), "n_bars": len(seg),
        "metrics": {"n_trades": int(len(r)), "expectancy_R": float(r.mean()) if len(r) else None,
                    "profit_factor": float(r[r > 0].sum() / -r[r < 0].sum()) if (r < 0).any() and (r > 0).any() else None,
                    "win_rate": float((r > 0).mean()) if len(r) else None, "realised_rr": (float(r[r > 0].mean() / -r[r <= 0].mean()) if (r > 0).any() and (r <= 0).any() and r[r <= 0].mean() < 0 else None), "worst_R": float(r.min()) if len(r) else None, "best_R": float(r.max()) if len(r) else None,
                    "max_drawdown": float(res.metrics.get("max_drawdown", 0.0)), "total_return": float(res.metrics.get("total_return", 0.0))},
        "daily": daily, "reasons": {k: {"n": v["n"], "mean_R": v["sumR"] / v["n"], "win_rate": v["wins"] / v["n"]} for k, v in sorted(reasons.items())},
        "bars": {"t": t_epoch, "o": [round(float(x), 5) for x in seg["open"]], "h": [round(float(x), 5) for x in seg["high"]],
                 "l": [round(float(x), 5) for x in seg["low"]], "c": [round(float(x), 5) for x in seg["close"]]},
        "trades": [{"i0": a, "i1": b, "side": t.side, "entry": float(t.entry), "exit": float(t.exit), "stop": float(t.stop) or None, "tp": float(t.take_profit) or None,
                    "r": round(float(t.r_nominal), 3), "reason": t.reason, "held": int(t.bars_held), "pnl": round(float(t.pnl), 2)}
                   for t, a, b in zip(trades, e_idx, x_idx)],
        "equity": [[str(t), float(v)] for t, v in zip(eq.index[::step], eq.to_numpy()[::step])],
        "buy_hold_return": float(seg["close"].iloc[-1] / seg["close"].iloc[0] - 1.0),
        "note": ("EXPLORATION : instrument hors de la spec préenregistrée de cette stratégie (règles figées, coûts mesurés ou hypothèses déclarées) ; aucun essai compté, aucune validité statistique. " if exploration else "") + "Fenêtre courte : ce rejeu sert à LIRE les trades ; seules les évaluations des portes (onglet Résultats) et le futur comptent pour juger. Coûts et risque hérités de la spec.",
    }
    if strategy.startswith("smc"):
        from ..strategies import smc
        out["zones"] = zones_payload(smc.zones(seg, scfg["rule"], scfg["params"]), seg.index[-1])
    with _lock:
        _cache[key] = out; _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return out


def _epoch(ts) -> int:
    return int(pd.Timestamp(ts).tz_localize(None).value // 10**9) if pd.Timestamp(ts).tzinfo is None else int(pd.Timestamp(ts).tz_convert("UTC").value // 10**9)


def zones_payload(zs: list, last_ts) -> list:
    """Zones OB/FVG sérialisées pour les graphiques : début (bougie OB), fin (déclenchement / invalidation / expiration ou dernière barre), niveaux, statut."""
    out = []
    for z in zs:
        out.append({"dir": z["dir"], "t0": _epoch(z["t0"]), "t_created": _epoch(z["t_created"]), "t1": _epoch(z["end"] if z["end"] is not None else last_ts), "open": z["end"] is None,
                    "ob": [z["ob_lo"], z["ob_hi"]], "fvg": [z["fvg_lo"], z["fvg_hi"]], "ce": z["ce"], "stop": z["stop"], "status": z["why"] or "active"})
    return out
