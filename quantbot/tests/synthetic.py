"""Marché synthétique RÉSERVÉ AUX TESTS (jamais utilisé par le produit ni pour un résultat de recherche)."""
import numpy as np
import pandas as pd

from quantbot.data.loaders import validate_ohlcv


def generate_synthetic(
    n: int = 1500, seed: int = 7, start_price: float = 100.0, freq: str = "1h", start: str = "2024-01-01"
) -> pd.DataFrame:
    """Marché synthétique avec changements de régime (tendance / volatilité)."""
    rng = np.random.default_rng(seed)
    rows, price, produced = [], start_price, 0
    while produced < n:
        seg = int(rng.integers(40, 160))
        mu, sigma = rng.normal(0, 0.0008), rng.uniform(0.004, 0.012)
        for _ in range(min(seg, n - produced)):
            o = price
            c = o * float(np.exp(rng.normal(mu, sigma)))
            wick = abs(rng.normal(0, sigma * 0.6))
            h = max(o, c) * (1 + wick * rng.random())
            lo = min(o, c) * (1 - wick * rng.random())
            rows.append((o, h, lo, c, float(rng.uniform(500, 1500))))
            price = c
            produced += 1
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    df.index = pd.date_range(start, periods=n, freq=freq)
    return validate_ohlcv(df)
