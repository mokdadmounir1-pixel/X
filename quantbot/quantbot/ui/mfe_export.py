"""Extraction de TOUS les trades pris (PAPER et réels) avec leur excursion favorable maximale (MFE : le plus haut atteint dans le sens du trade) et leur excursion défavorable (MAE), pour analyse.

Pour chaque trade (clos ou ouvert), sur les barres RÉELLES comprises entre l'entrée et la sortie : MFE = max(haut) - entrée (achat) ou entrée - min(bas) (vente), en prix et en R (R = |entrée - stop|) ; « le plus haut s'il était positif » = MFE > 0
(un trade perdant qui a d'abord gagné est signalé). Résumé : somme des MFE de tous les trades, des perdants, des trades au TP ; give-back = MFE - résultat. Lecture seule, aucune donnée inventée : sans barres couvrant le trade, la ligne est marquée `sans_barres`.
Limite : l'ordre des événements DANS une barre est inconnu (un trade stoppé dans la barre où il a touché son plus haut peut avoir fait le plus bas avant) ; la MFE est donc une borne haute pour cette barre.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..gui.book import build_book

COLUMNS = ["id", "runner", "strategy_code", "symbol", "side", "status", "reason", "entry_time", "exit_time", "entry", "sl", "tp", "exit", "size", "pnl", "r", "risk_price", "mfe_price", "mfe_r", "mae_r",
           "mfe_positive", "loser_with_positive_mfe", "giveback_r", "bars_to_mfe", "bars_held", "is_tp", "bars_source", "note"]


def _bars(root: Path, symbol: str, tf: str, cache: dict) -> Optional[pd.DataFrame]:
    key = (symbol, tf)
    if key in cache:
        return cache[key]
    from ..data.coinbase import load_utc_csv
    from ..data.mt5 import load_mt5_csv
    df = None
    for origin, kind in (("live", "mt5"), ("real", "mt5"), ("crypto", "utc")):
        f = Path(root) / "data" / origin / f"{symbol}_{tf}.csv"
        if f.exists():
            try:
                df = load_utc_csv(f) if kind == "utc" else load_mt5_csv(f); break
            except Exception:
                df = None
    cache[key] = df; return df


def _tf_for(strategy_code: str, root: Path, cache: dict) -> str:
    """M1 pour les stratégies dont la spec le déclare, sinon M15."""
    if "tfmap" not in cache:
        m = {}
        from ..strategies.build import strategy_code as sc
        for f in sorted((Path(root) / "specs").glob("*.json")):
            try:
                for k, v in (json.loads(f.read_text(encoding="utf-8")).get("strategies") or {}).items():
                    if isinstance(v, dict) and v.get("timeframe"):
                        m[sc(k)] = v["timeframe"]
            except (OSError, ValueError):
                continue
        cache["tfmap"] = m
    return cache["tfmap"].get(strategy_code, "M15")


def excursions(df: pd.DataFrame, side: str, entry: float, stop: float, t0, t1) -> dict:
    sub = df[(df.index >= pd.Timestamp(t0)) & (df.index <= pd.Timestamp(t1))]
    if sub.empty or not np.isfinite(entry) or stop is None or entry == stop:
        return {}
    risk = abs(entry - stop); long = side == "long"
    fav = (sub["high"].to_numpy(float) - entry) if long else (entry - sub["low"].to_numpy(float)); adv = (entry - sub["low"].to_numpy(float)) if long else (sub["high"].to_numpy(float) - entry)
    k = int(np.argmax(fav)); mfe = max(float(fav[k]), 0.0); mae = max(float(adv.max()), 0.0)
    return {"risk": risk, "mfe_price": mfe, "mfe_r": mfe / risk, "mae_r": mae / risk, "bars_to_mfe": k, "bars_held": int(len(sub))}


def build_export(root: Path, period: str = "all") -> dict:
    root = Path(root); book = build_book(root, period); cache: dict = {}; rows = []
    for t in book["rows"]:
        r = {c: None for c in COLUMNS}
        r.update(id=t["id"], runner=t["runner"], strategy_code=t["strategy_code"], symbol=t["symbol"], side=t["side"], status=t["status"], reason=t.get("reason"), entry_time=t["entry_time"], exit_time=t["exit_time"],
              entry=t["entry"], sl=t["sl"], tp=t["tp"], exit=t["exit"], size=t["size"], pnl=t["pnl"], r=t["r"], is_tp=bool(t.get("reason") == "take_profit"))
        df = _bars(root, t["symbol"], _tf_for(t["strategy_code"], root, cache), cache)
        t1 = t["exit_time"] or (df.index[-1] if df is not None and len(df) else None)
        if df is None or t1 is None or t["entry_time"] is None or t["sl"] is None or t["entry"] is None:
            r["note"] = "sans_barres"; rows.append(r); continue
        e = excursions(df, t["side"], float(t["entry"]), float(t["sl"]), t["entry_time"], t1)
        if not e:
            r["note"] = "sans_barres"; rows.append(r); continue
        r.update(risk_price=e["risk"], mfe_price=e["mfe_price"], mfe_r=e["mfe_r"], mae_r=e["mae_r"], bars_to_mfe=e["bars_to_mfe"], bars_held=e["bars_held"], bars_source=("M1" if "M1" in _tf_for(t["strategy_code"], root, cache) else "M15"))
        r["mfe_positive"] = bool(e["mfe_r"] > 0); rr = t["r"]
        if rr is not None:
            r["loser_with_positive_mfe"] = bool(rr <= 0 and e["mfe_r"] > 0); r["giveback_r"] = e["mfe_r"] - rr
        if t["open"]:
            r["note"] = "ouvert : MFE depuis l'entrée jusqu'à la dernière barre"
        rows.append(r)
    return {"rows": rows, "summary": summarize(rows), "generated_from": "livre des trades PAPER/réels + barres réelles (data/live, data/real, data/crypto)"}


def _agg(rs: list) -> dict:
    m = [x["mfe_r"] for x in rs if x["mfe_r"] is not None]
    return {"n": len(rs), "sum_mfe_r": float(np.sum(m)) if m else 0.0, "mean_mfe_r": float(np.mean(m)) if m else None, "sum_r": float(np.sum([x["r"] for x in rs if x["r"] is not None])) if rs else 0.0}


def summarize(rows: list) -> dict:
    closed = [x for x in rows if x["status"] != "OUVERT"]; have = [x for x in closed if x["mfe_r"] is not None]
    losers = [x for x in have if x["r"] is not None and x["r"] <= 0]; lwm = [x for x in losers if x["mfe_r"] > 0]; tps = [x for x in have if x["is_tp"]]
    def gb(rs): return float(np.sum([x["giveback_r"] for x in rs if x["giveback_r"] is not None])) if rs else 0.0
    out = {"trades_closed": len(closed), "trades_open": len(rows) - len(closed), "closed_with_bars": len(have), "closed_without_bars": len(closed) - len(have),
           "all_closed": {**_agg(have), "giveback_r": gb(have)}, "losers": {**_agg(losers), "giveback_r": gb(losers)},
           "losers_with_positive_mfe": {**_agg(lwm), "share_of_losers": (len(lwm) / len(losers)) if losers else None, "n_mfe_ge_0_5r": int(sum(x["mfe_r"] >= 0.5 for x in lwm)), "n_mfe_ge_1r": int(sum(x["mfe_r"] >= 1.0 for x in lwm))},
           "take_profit": {**_agg(tps), "giveback_r": gb(tps)}, "by_strategy": {}}
    for k in sorted({x["strategy_code"] for x in have}):
        sub = [x for x in have if x["strategy_code"] == k]; ls = [x for x in sub if x["r"] is not None and x["r"] <= 0]
        out["by_strategy"][k] = {"n": len(sub), "sum_r": float(np.sum([x["r"] for x in sub if x["r"] is not None])), "sum_mfe_r": float(np.sum([x["mfe_r"] for x in sub])), "n_tp": int(sum(x["is_tp"] for x in sub)),
                                 "n_losers": len(ls), "n_losers_positive_mfe": int(sum(x["mfe_r"] > 0 for x in ls)), "sum_mfe_r_losers": float(np.sum([x["mfe_r"] for x in ls]))}
    return out


def to_csv(rows: list) -> str:
    buf = io.StringIO(); w = csv.writer(buf, lineterminator="\n"); w.writerow(COLUMNS)
    for r in rows:
        w.writerow(["" if r[c] is None else (round(r[c], 6) if isinstance(r[c], float) else r[c]) for c in COLUMNS])
    return buf.getvalue()
