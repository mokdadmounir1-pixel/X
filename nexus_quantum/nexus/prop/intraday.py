"""Strategies de session M5 (ORB, momentum intraday), couts reels via spread des donnees.

Conventions (barres = prix BID; spread en prix):
- achat au ask = bid + spread ; vente au bid. Un long paie le spread a l'entree, un short a la sortie.
- decision a la cloture de la barre i, FILL a l'ouverture de i+1 (pas de look-ahead).
- stop verifie sur extremes de barre; si stop et cible dans la meme barre: STOP d'abord (conservateur);
  gap au-dela du stop: fill a l'ouverture (perte > 1R possible).
- slippage additionnel = slip_frac * spread median, par cote [HYPOTHESE].
- pas de position overnight: sortie avant la fermeture de session.
Heure serveur = EET/EEST [VERIFIE par profil de volume: pics 10:00 GER40, 16:30 US]; jour FTMO = ts-60min.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from .mdata import Bars

DAY_OFFSET_MIN = 60   # minuit CET = 01:00 serveur [HYPOTHESE a verifier]

SESSIONS = {          # minutes serveur: (ouverture, fin)
    "GER40": (10 * 60, 18 * 60 + 30), "GBPUSD": (10 * 60, 18 * 60 + 30),
    "XAUUSD": (10 * 60, 18 * 60 + 30), "US100": (16 * 60 + 30, 23 * 60),
    "US500": (16 * 60 + 30, 23 * 60),
}


@dataclass(frozen=True)
class Trade:
    symbol: str
    day: int
    r: float        # resultat en multiples du risque, frais inclus
    mae_r: float    # pire excursion adverse en R (<= 0), conservateur


def _day_index(b: Bars) -> dict[int, dict[int, int]]:
    d: dict[int, dict[int, int]] = {}
    for i, t in enumerate(b.ts):
        d.setdefault((t - DAY_OFFSET_MIN) // 1440, {})[t % 1440] = i
    return d


def _spread_floor(b: Bars) -> float:
    pos = sorted(s for s in b.spread if s > 0)
    return pos[len(pos) // 10]          # P10 des spreads positifs (les 0 sont des artefacts)


def orb_trades(b: Bars, range_min: int, exit_mode: str, slip_frac: float = 0.25,
               max_cost_over_risk: float = 0.15) -> list[Trade]:
    """exit_mode: 'EOD' ou '2R'. Un trade max par jour; range = premieres range_min minutes."""
    if exit_mode not in ("EOD", "2R"):
        raise ValueError(exit_mode)
    op, end = SESSIONS[b.symbol]
    floor = _spread_floor(b)
    slip = slip_frac * median(s for s in b.spread if s > 0)
    out = []
    for day, bars in _day_index(b).items():
        rng_idx = [bars.get(m) for m in range(op, op + range_min, 5)]
        if any(i is None for i in rng_idx):
            continue                                   # donnees incompletes / jour ferme
        hi, lo = max(b.h[i] for i in rng_idx), min(b.l[i] for i in rng_idx)
        sess = [bars[m] for m in range(op + range_min, end, 5) if m in bars]
        entry_k = None
        for k, i in enumerate(sess[:-1]):              # signal a la cloture de i
            d = 1 if b.c[i] > hi else -1 if b.c[i] < lo else 0
            if d:
                entry_k = k + 1
                break
        if entry_k is None:
            continue
        j = sess[entry_k]                              # fill a l'ouverture de la barre suivante
        sp = max(b.spread[j], floor)
        entry = b.o[j] + sp + slip if d == 1 else b.o[j] - slip
        stop = lo if d == 1 else hi
        risk = abs(entry - stop)
        if risk <= 0 or (sp + 2 * slip) / risk > max_cost_over_risk:
            continue                                   # filtre de cout: pas de re-entree ce jour
        tgt = entry + d * 2 * risk if exit_mode == "2R" else None
        mae, exit_px = 0.0, None
        for i in sess[entry_k:]:
            sp = max(b.spread[i], floor)
            if d == 1:
                mae = min(mae, (b.l[i] - entry) / risk)
                if b.o[i] <= stop: exit_px = b.o[i] - slip; break
                if b.l[i] <= stop: exit_px = stop - slip; break
                if tgt is not None and b.h[i] >= tgt: exit_px = tgt - slip; break
            else:
                mae = min(mae, (entry - (b.h[i] + sp)) / risk)
                if b.o[i] + sp >= stop: exit_px = b.o[i] + sp + slip; break
                if b.h[i] + sp >= stop: exit_px = stop + slip; break
                if tgt is not None and b.l[i] + sp <= tgt: exit_px = tgt + slip; break
        if exit_px is None:                            # sortie en fin de session
            i = sess[-1]; sp = max(b.spread[i], floor)
            exit_px = b.c[i] - slip if d == 1 else b.c[i] + sp + slip
        r = d * (exit_px - entry) / risk
        out.append(Trade(b.symbol, day, r, min(mae, r)))
    return out


def intraday_momentum_trades(b: Bars, first_min: int = 30, last_min: int = 30,
                             slip_frac: float = 0.25, lookback: int = 60) -> list[Trade]:
    """Gao-Han-Li-Zhou (2018): le rendement des first_min premieres minutes (depuis la cloture
    veille) predit les last_min dernieres [HYPOTHESE]. Stop = 2x moyenne glissante (passee)
    des |mouvements| de fin de session; taille par risque."""
    op, end = SESSIONS[b.symbol]
    floor = _spread_floor(b)
    slip = slip_frac * median(s for s in b.spread if s > 0)
    days = _day_index(b)
    prev_close, hist, out = None, [], []
    for day in sorted(days):
        bars = days[day]
        last = bars.get(end - 5)
        sig_i = bars.get(op + first_min - 5)
        in_i = bars.get(end - last_min)
        ok = last is not None and sig_i is not None and in_i is not None
        if ok and prev_close is not None and len(hist) >= 20:
            r1 = b.c[sig_i] / prev_close - 1
            d = 1 if r1 > 0 else -1 if r1 < 0 else 0
            m = sum(hist[-lookback:]) / len(hist[-lookback:])    # uniquement du passe
            if d and m > 0:
                sp = max(b.spread[in_i], floor)
                entry = b.o[in_i] + sp + slip if d == 1 else b.o[in_i] - slip
                risk = 2 * m * entry
                stop = entry - d * risk
                mae, exit_px = 0.0, None
                for mn in range(end - last_min, end, 5):
                    i = bars.get(mn)
                    if i is None:
                        continue
                    sp = max(b.spread[i], floor)
                    if d == 1:
                        mae = min(mae, (b.l[i] - entry) / risk)
                        if b.o[i] <= stop: exit_px = b.o[i] - slip; break
                        if b.l[i] <= stop: exit_px = stop - slip; break
                    else:
                        mae = min(mae, (entry - (b.h[i] + sp)) / risk)
                        if b.o[i] + sp >= stop: exit_px = b.o[i] + sp + slip; break
                        if b.h[i] + sp >= stop: exit_px = stop + slip; break
                if exit_px is None:
                    sp = max(b.spread[last], floor)
                    exit_px = b.c[last] - slip if d == 1 else b.c[last] + sp + slip
                r = d * (exit_px - entry) / risk
                if (max(b.spread[in_i], floor) + 2 * slip) / risk <= 0.15:
                    out.append(Trade(b.symbol, day, r, min(mae, r)))
        if ok:
            hist.append(abs(b.c[last] / b.o[in_i] - 1))
            prev_close = b.c[last]
    return out


def daily_series(trades: list[Trade], days: list[int], risk_pct: float):
    """(ret, worst) par jour: ret = somme risk_pct*r ; worst = somme risk_pct*mae (borne conservatrice)."""
    ret = {d: 0.0 for d in days}; worst = {d: 0.0 for d in days}
    for t in trades:
        ret[t.day] += risk_pct * t.r
        worst[t.day] += risk_pct * t.mae_r
    return [ret[d] for d in days], [worst[d] for d in days]
