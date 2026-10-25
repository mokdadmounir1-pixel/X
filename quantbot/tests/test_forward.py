import numpy as np
import pandas as pd

from quantbot.config import Settings
from quantbot.lab.forward import evaluate_forward, forward_trades
from quantbot.strategies.events import Event, EventSignalEngine
from tests.synthetic import generate_synthetic


def setup(n=3000, every=25):
    df = generate_synthetic(n, seed=5, freq="15min", start="2024-03-04")
    s = Settings.from_dict({"backtest": {"max_hold_bars": 10}})
    atr = (df["high"] - df["low"]).rolling(14).mean()
    evs = [Event(df.index[i], "bullish", float(df.close.iloc[i] - 2 * atr.iloc[i]), name="t") for i in range(60, n - 5, every) if np.isfinite(atr.iloc[i])]
    return df, s, evs


def test_only_trades_after_the_freeze_are_counted():
    df, s, evs = setup()
    freeze = df.index[2000]
    t = forward_trades(df, s, EventSignalEngine(s, evs), freeze)
    assert t and all(pd.Timestamp(x.entry_time) > freeze for x in t)
    assert len(t) < len(forward_trades(df, s, EventSignalEngine(s, evs), df.index[100]))


def test_performance_is_withheld_below_threshold_and_disclosed_above():
    df, s, evs = setup()
    t = forward_trades(df, s, EventSignalEngine(s, evs), df.index[2000])
    low = evaluate_forward(t, min_trades=10_000)
    assert low["disclosed"] is False and set(low) == {"n_forward_trades", "min_trades", "disclosed", "note"}      # aucune métrique de performance
    hi = evaluate_forward(t, min_trades=len(t))
    assert hi["disclosed"] and hi["verdict"] in ("CONFIRMÉ", "NON CONFIRMÉ") and "expectancy_R" in hi
