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
