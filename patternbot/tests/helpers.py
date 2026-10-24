import numpy as np
import pandas as pd

K = 300.0  # miroir de prix : p' = K - p (reste positif)


def make_index(n):
    return pd.date_range("2024-01-01", periods=n, freq="1h")


def frame(rows):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["volume"] = 1000.0
    df.index = make_index(len(df))
    return df


def mirror(rows):
    return [(K - o, K - l, K - h, K - c) for o, h, l, c in rows]


def downtrend(n=30, start=130.0, step=1.0, wick=0.2):
    rows, p = [], start
    for _ in range(n):
        c = p - step
        rows.append((p, p + wick, c - wick, c))
        p = c
    return rows


def bar(o, c, h=None, l=None, wick=0.2):
    return (o, h if h is not None else max(o, c) + wick, l if l is not None else min(o, c) - wick, c)


def from_waypoints(prices, bars_per_leg=8, tail=4, wick=0.15, lead=6):
    """Série en lignes brisées passant par `prices`.

    `lead` barres avant le 1er point (sinon il ne peut pas être un pivot) et
    `tail` barres après le dernier (sinon le pivot n'est pas confirmé).
    """
    first_dir = 1 if prices[1] > prices[0] else -1
    amp = abs(prices[1] - prices[0]) * 0.3
    closes = list(np.linspace(prices[0] + first_dir * amp, prices[0], lead + 1))
    for a, b in zip(prices[:-1], prices[1:]):
        closes += list(np.linspace(a, b, bars_per_leg + 1)[1:])
    sign = 1 if prices[-1] < prices[-2] else -1  # dernier pivot bas -> rebond
    step = abs(prices[-1] - prices[-2]) * 0.02
    for k in range(tail):
        closes.append(closes[-1] + sign * step)
    rows, prev = [], closes[0]
    for c in closes:
        rows.append((prev, max(prev, c) + wick, min(prev, c) - wick, c))
        prev = c
    return rows
