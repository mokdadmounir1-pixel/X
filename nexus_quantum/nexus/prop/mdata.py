"""Chargement + audit qualite des barres M5 FTMO (heure serveur, spread en points).

Heure serveur FTMO supposee = Europe/Prague-like (CE(S)T) [HYPOTHESE a verifier];
les barres sont indexees par minute-epoch 'naive' (aucune conversion de fuseau).
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Bars:
    symbol: str
    sha256: str
    ts: list[int]        # minutes depuis epoch (heure serveur 'naive')
    o: list[float]; h: list[float]; l: list[float]; c: list[float]
    spread: list[float]  # en unites de prix


def _minutes(s: str) -> int:
    return int(datetime.strptime(s, "%Y.%m.%d %H:%M").replace(tzinfo=timezone.utc).timestamp() // 60)


def load_m5(path: str | Path, symbol: str) -> Bars:
    raw = Path(path).read_bytes()
    b = Bars(symbol, hashlib.sha256(raw).hexdigest(), [], [], [], [], [], [])
    for r in csv.DictReader(raw.decode("utf-8-sig").splitlines()):
        b.ts.append(_minutes(r["heure_serveur"]))
        b.o.append(float(r["open"])); b.h.append(float(r["high"]))
        b.l.append(float(r["low"])); b.c.append(float(r["close"]))
        b.spread.append(float(r["spread_prix"]))
    return b


def audit(b: Bars) -> dict:
    n = len(b.ts)
    dup = sum(1 for i in range(1, n) if b.ts[i] == b.ts[i - 1])
    back = sum(1 for i in range(1, n) if b.ts[i] < b.ts[i - 1])
    bad_ohlc = sum(1 for i in range(n) if not (b.h[i] >= max(b.o[i], b.c[i]) and b.l[i] <= min(b.o[i], b.c[i])))
    nonpos = sum(1 for i in range(n) if min(b.o[i], b.h[i], b.l[i], b.c[i]) <= 0)
    gaps = [b.ts[i] - b.ts[i - 1] for i in range(1, n) if b.ts[i] - b.ts[i - 1] > 5]
    big_gaps = sum(1 for g in gaps if g > 60 * 6)            # > 6 h (nuits/week-ends exclus ci-dessous)
    nul_spread = sum(1 for s in b.spread if s <= 0)
    jumps = sorted(abs(b.c[i] / b.c[i - 1] - 1) for i in range(1, n))
    srt = sorted(b.spread)
    return dict(symbol=b.symbol, n=n, first=b.ts[0], last=b.ts[-1], dup=dup, backwards=back,
                bad_ohlc=bad_ohlc, nonpos=nonpos, n_gaps_gt5min=len(gaps), n_gaps_gt6h=big_gaps,
                spread_zero_or_neg=nul_spread, spread_med=srt[n // 2], spread_p99=srt[int(n * .99)],
                max_bar_jump=jumps[-1], p9999_jump=jumps[int(n * .9999)])
