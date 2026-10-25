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


# --- marché avec edge planté + signal « oracle » (teste la chaîne moteur/stats, pas les détecteurs) -------------
def planted_frame(n=3000, seed=0, edge=True, sigma=0.004, drift=0.0025, tell_prob=0.04, horizon=8):
    """Marche aléatoire quotidienne ; sur certaines barres (volume=5000) une dérive s'ensuit.
    edge=True : dérive haussière ; edge=False : sens aléatoire (le « tell » ne prédit rien)."""
    rng = np.random.default_rng(seed)
    ret = rng.normal(0, sigma, n)
    vol = np.full(n, 1000.0)
    t = 20
    while t < n - horizon - 2:
        if rng.random() < tell_prob:
            vol[t] = 5000.0
            sign = 1.0 if edge else float(rng.choice([-1.0, 1.0]))
            ret[t + 1: t + 1 + horizon] += sign * drift
            t += horizon + 2
        else:
            t += 1
    close = 100.0 * np.exp(np.cumsum(ret))
    open_ = np.concatenate(([100.0], close[:-1]))
    wick = np.abs(rng.normal(0, sigma * 0.5, n)) * close
    df = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + wick,
                       "low": np.minimum(open_, close) - wick, "close": close, "volume": vol})
    df.index = pd.date_range("2016-01-01", periods=n, freq="1D")
    return df


class OracleSignals:
    """Signal haussier sur chaque « tell » : remplace les détecteurs pour tester le reste de la chaîne."""

    def evaluate(self, window, htf=None):
        from quantbot.indicators.core import atr
        from quantbot.patterns.base import PatternMatch
        from quantbot.signals.engine import Signal
        if window["volume"].iloc[-1] < 5000:
            return None
        a = float(atr(window, 14).iloc[-1])
        m = PatternMatch("oracle", "candle", "bullish", 0.9, 0, len(window) - 1)
        return Signal("bullish", 0.9, float(window["close"].iloc[-1]), a, window.index[-1], [m])
