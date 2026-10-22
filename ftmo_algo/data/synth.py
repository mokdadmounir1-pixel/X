"""Données SYNTHÉTIQUES M5 (toujours étiquetées comme telles). Marche aléatoire à volatilité
clusterisée, saisonnalité intrajournalière, gaps de week-end, chocs d'annonces (NFP).
Par défaut AUCUN edge : sert à calibrer le taux de faux PASS. `persistence>0` plante une
dérive de tendance persistante (test de puissance des portes)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from ..instruments import SPECS
from ..timeutil import ns

BASE = {"US500": (4500, .16), "US100": (15000, .22), "US30": (35000, .15), "GER40": (16000, .17),
        "XAUUSD": (2000, .15), "EURUSD": (1.08, .07), "GBPUSD": (1.26, .08), "AUDUSD": (.66, .09),
        "USDJPY": (150, .09), "AUDCAD": (.90, .06), "GBPJPY": (190, .11), "BTCUSD": (30000, .55)}
FREQ = "5min"


def nfp_times(start, end) -> list[pd.Timestamp]:
    """Premier vendredi du mois, 08:30 New York (approximation de la règle NFP) -> UTC."""
    out = []
    for m in pd.period_range(start, end, freq="M"):
        d = pd.Timestamp(m.start_time)
        d = d + pd.Timedelta(days=(4 - d.weekday()) % 7)
        t = pd.Timestamp(d.year, d.month, d.day, 8, 30, tz="America/New_York").tz_convert("UTC")
        if start <= t <= end:
            out.append(t)
    return out


def make_series(name: str, start="2021-01-04", years=4.0, seed=0, persistence=0.0,
                shared: np.ndarray | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    spec = SPECS[name]
    px0, avol = BASE[name]
    idx = pd.date_range(start, periods=int(years * 365 * 288), freq=FREQ, tz="UTC")
    if spec.kind != "crypto":  # week-end fermé : ven 21:55 -> dim 22:00 UTC
        wd, h = idx.weekday, idx.hour + idx.minute / 60
        closed = (wd == 5) | ((wd == 4) & (h >= 22)) | ((wd == 6) & (h < 22))
        idx = idx[~closed]
    n = len(idx)
    hour = (idx.hour + idx.minute / 60).to_numpy()
    seas = 0.55 + 0.9 * np.exp(-((hour - 8.5) / 2.2) ** 2) + 1.1 * np.exp(-((hour - 14.5) / 2.5) ** 2)
    seas = seas / np.sqrt(np.mean(seas ** 2))
    day = ns(idx.normalize()) // 86_400_000_000_000
    ud, inv = np.unique(day, return_inverse=True)
    lv = np.zeros(len(ud)); e = rng.standard_normal(len(ud))
    for i in range(1, len(ud)):
        lv[i] = 0.97 * lv[i - 1] + 0.22 * e[i]
    dvol = avol / np.sqrt(252) * np.exp(lv - lv.var() / 2)  # vol quotidienne
    bar_vol = dvol[inv] / np.sqrt(288 * (5 / 7 if spec.kind != "crypto" else 1)) * seas
    z = rng.standard_normal(n)
    if shared is not None and len(shared) >= n:
        z = 0.6 * shared[:n] + 0.8 * z
    r = bar_vol * z
    if persistence > 0:  # dérive de tendance persistante (demi-vie ≈ 1,5 jour)
        a = np.exp(-np.log(2) / (288 * 1.5)); dr = np.zeros(n); g = rng.standard_normal(n) * np.sqrt(1 - a * a)
        for i in range(1, n):
            dr[i] = a * dr[i - 1] + g[i]
        r = r + persistence * bar_vol * dr
    # chocs d'annonce
    ts = ns(idx)
    for t in nfp_times(idx[0], idx[-1]):
        k = np.searchsorted(ts, t.value)
        if k < n - 12:
            s = rng.choice([-1, 1]); r[k] += s * 6 * bar_vol[k] * rng.uniform(.6, 1.4)
            r[k + 1:k + 6] += s * 1.2 * bar_vol[k + 1:k + 6] * persistence * 4  # suite de réaction (si edge planté)
    # gaps de week-end
    gap = np.zeros(n)
    if spec.kind != "crypto":
        newwk = np.r_[False, (np.diff(ts) > 36 * 3600 * 10**9)]
        gap[newwk] = rng.standard_normal(newwk.sum()) * dvol[inv][newwk] * 0.8
    lp = np.log(px0) + np.cumsum(r + gap)
    close = np.exp(lp)
    opn = np.r_[px0, close[:-1]] * np.exp(gap)
    hi = np.maximum(opn, close) * np.exp(np.abs(rng.standard_normal(n)) * bar_vol * 0.6)
    lo = np.minimum(opn, close) * np.exp(-np.abs(rng.standard_normal(n)) * bar_vol * 0.6)
    tick = spec.tick
    f = lambda x: np.round(x / tick) * tick
    sp = spec.spread * (1.0 + 2.5 * ((hour >= 21) | (hour < 1)) + 0.5 * (seas < .8))
    df = pd.DataFrame({"open": f(opn), "high": f(hi), "low": f(lo), "close": f(close),
                       "volume": np.maximum(1, (seas * 100 * rng.lognormal(0, .4, n))).astype(int),
                       "spread": sp}, index=idx)
    df.index.name = "time"
    df.attrs.update(source="SYNTHETIC", instrument=name, seed=seed, persistence=persistence)
    return df


def make_universe(names, seed=0, years=4.0, persistence=0.0, start="2021-01-04"):
    """Univers synthétique avec facteur commun entre actifs du même groupe."""
    rng = np.random.default_rng(seed + 991)
    shared = {g: rng.standard_normal(int(years * 365 * 288) + 10) for g in sorted({SPECS[n].group for n in names})}   # ordre déterministe
    return {n: make_series(n, start, years, seed * 100 + i, persistence, shared[SPECS[n].group])
            for i, n in enumerate(names)}
