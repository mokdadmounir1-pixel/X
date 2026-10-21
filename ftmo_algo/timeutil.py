import numpy as np
import pandas as pd


def ns(idx) -> np.ndarray:
    """Index/Series de dates -> int64 en nanosecondes (indépendant de l'unité pandas)."""
    idx = pd.DatetimeIndex(idx)
    return idx.as_unit("ns").asi8
