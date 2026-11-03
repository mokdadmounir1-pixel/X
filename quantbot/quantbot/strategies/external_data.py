"""Chargement des données externes pour les stratégies qui en dépendent (COT, FRED, profondeur du carnet). Sans fichier : liste vide et raison explicite, JAMAIS de valeur inventée."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..gui.paths import app_root

REQUIRES = {"cot_extremes": ["data/external/cot_gold.csv"], "macro_tips": ["data/external/fred_DFII10.csv"], "ofi_depth": ["data/live/depth/XAUUSD_*.jsonl"], "hawk_tox": ["data/live/ticks/XAUUSD_*.csv"], "leadlag_k": ["data/live/DXY_M1.csv", "data/live/USDJPY_M1.csv"]}


def missing(strategy: str, root: Optional[Path] = None) -> list[str]:
    root = Path(root or app_root()); out = []
    for pat in REQUIRES.get(strategy, []):
        if not list(root.glob(pat)):
            out.append(pat)
    return out


def load_cot(root: Optional[Path] = None) -> Optional[pd.DataFrame]:
    f = Path(root or app_root()) / "data" / "external" / "cot_gold.csv"
    if not f.exists():
        return None
    d = pd.read_csv(f); d["available_from"] = pd.to_datetime(d["available_from"]); return d.set_index("available_from").sort_index()


def load_fred(series: str, root: Optional[Path] = None) -> Optional[pd.Series]:
    """CSV (date, value) d'une série FRED ; les valeurs « . » (manquantes) sont écartées. Disponible le JOUR SUIVANT (publication en différé)."""
    f = Path(root or app_root()) / "data" / "external" / f"fred_{series}.csv"
    if not f.exists():
        return None
    d = pd.read_csv(f); d.columns = [c.lower() for c in d.columns]; v = pd.to_numeric(d["value"], errors="coerce"); s = pd.Series(v.to_numpy(), index=pd.to_datetime(d["date"])).dropna()
    s.index = s.index + pd.Timedelta(days=1); return s.sort_index()


def load_depth_imbalance(root: Optional[Path] = None, symbol: str = "XAUUSD", levels: int = 5, bucket: str = "15min") -> Optional[pd.Series]:
    """Déséquilibre moyen du carnet (somme des tailles bid - ask) / total sur les `levels` meilleurs niveaux, par tranche de `bucket` (UTC naïf)."""
    files = sorted((Path(root or app_root()) / "data" / "live" / "depth").glob(f"{symbol}_*.jsonl"))
    if not files:
        return None
    t, v = [], []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line); b = sum(x[1] for x in r["bids"][:levels]); a = sum(x[1] for x in r["asks"][:levels])
                if b + a > 0:
                    t.append(r["t"]); v.append((b - a) / (b + a))
            except (ValueError, KeyError, IndexError):
                continue
    if not t:
        return None
    s = pd.Series(v, index=pd.to_datetime(t, unit="s")); return s.resample(bucket).mean().dropna()


def load_ticks(symbol: str, root: Optional[Path] = None, rule: str = "eu_dst") -> Optional[pd.DataFrame]:
    """Ticks RÉELS collectés par le terminal (data/live/ticks/<SYMBOLE>_<AAAAMMJJ>.csv) : index = UTC naïf reconstruit depuis l'horloge courtier (time_msc), colonnes bid, ask, mid. None si aucun fichier."""
    from ..data.mt5 import broker_clock_to_utc
    files = sorted((Path(root or app_root()) / "data" / "live" / "ticks").glob(f"{symbol}_*.csv"))
    if not files:
        return None
    d = pd.concat([pd.read_csv(f, usecols=["time_msc", "bid", "ask"]) for f in files], ignore_index=True).drop_duplicates("time_msc").sort_values("time_msc")
    d = d[(d["bid"] > 0) & (d["ask"] >= d["bid"])]
    if d.empty:
        return None
    clock = pd.DatetimeIndex(pd.to_datetime(d["time_msc"], unit="ms")); idx = broker_clock_to_utc(clock, rule)
    out = pd.DataFrame({"bid": d["bid"].to_numpy(float), "ask": d["ask"].to_numpy(float)}, index=idx); out["mid"] = (out["bid"] + out["ask"]) / 2.0
    return out[~out.index.duplicated(keep="last")].sort_index()


def load_bars(symbol: str, tf: str = "M1", root: Optional[Path] = None) -> Optional[pd.DataFrame]:
    """Barres synchronisées d'un autre instrument (data/live/<SYMBOLE>_<TF>.csv, horloge courtier -> UTC) ; None si absent."""
    from ..data.mt5 import load_mt5_csv
    f = Path(root or app_root()) / "data" / "live" / f"{symbol}_{tf}.csv"
    return load_mt5_csv(f) if f.exists() else None
