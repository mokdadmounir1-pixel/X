"""Pilote de simulation prospective : lit un flux de barres, fait tourner les
moteurs de signaux du bot FX et envoie signaux/barres au livre virtuel.

Le flux peut être une relecture de données (marquer `source`) ; le moteur ne
fait pas la différence, mais le rapport doit la faire."""
from __future__ import annotations

import pandas as pd

from fx_liquidity_bot.config import StrategyConfig
from fx_liquidity_bot.engine.pair_engine import PairSignalEngine, prepare_dataframe

from .book import Signal, VirtualBook

STRATEGY_ID = "fx_liquidity_sweep_fvg"


def strategy_params(cfg: StrategyConfig) -> dict:
    d = dict(vars(cfg))
    d["score_weights"] = vars(cfg.score_weights)
    d["session_windows"] = [vars(s) for s in cfg.session_windows]
    return d


def run(book: VirtualBook, data: dict, cfg: StrategyConfig, stop_after: pd.Timestamp | None = None) -> None:
    prepared = {p: prepare_dataframe(df, cfg) for p, df in data.items()}
    engines = {p: PairSignalEngine(p, cfg) for p in prepared}
    idx = {p: {ts: i for i, ts in enumerate(df.index)} for p, df in prepared.items()}
    for ts in sorted(set().union(*[set(df.index) for df in prepared.values()])):
        if stop_after is not None and ts > stop_after:
            return
        cands = []
        for p, df in prepared.items():
            j = idx[p].get(ts)
            if j is None:
                continue
            row = df.iloc[j]
            spread = cfg.typical_spread_pips[p]  # substitut de recherche, pas un spread mesuré
            book.on_bar(p, ts, row.open, row.high, row.low, row.close, spread)
            c = engines[p].process_bar(df, j)
            if c is not None:
                cands.append(c)
        for c in sorted(cands, key=lambda c: c.score, reverse=True):
            sid = f"{STRATEGY_ID}:{c.pair}:{c.signal_time.isoformat()}:{c.direction}"
            book.submit_signal(Signal(sid, c.signal_time, c.pair, c.direction, c.stop_price,
                                      c.target_price, STRATEGY_ID,
                                      {"score": round(c.score, 1), "rr": round(c.rr, 2), "session": c.session}))
