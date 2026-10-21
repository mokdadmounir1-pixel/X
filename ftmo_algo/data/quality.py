"""Contrôle qualité des données + rééchantillonnage multi-timeframe sans fuite."""
from __future__ import annotations
import numpy as np
import pandas as pd
from ..instruments import SPECS
from ..timeutil import ns

TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def resample_ohlc(df: pd.DataFrame, tf: str, offset: str = "0h") -> pd.DataFrame:
    """Barres agrégées indexées par leur HEURE D'OUVERTURE ; colonne `close_time` = ouverture + durée.
    Une barre n'est utilisable qu'à partir de `close_time` (voir align_htf)."""
    m = TF_MIN[tf]
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "spread" in df.columns:
        agg["spread"] = "mean"
    r = df.resample(f"{m}min", origin="epoch", offset=offset, label="left", closed="left").agg(agg).dropna(subset=["open"])
    r["close_time"] = r.index + pd.Timedelta(minutes=m)
    r.attrs.update(df.attrs)
    return r


def align_htf(base_close_ns: np.ndarray, htf: pd.DataFrame) -> np.ndarray:
    """Pour chaque barre de base (instant de clôture donné), indice de la dernière barre HTF
    DÉJÀ CLOSE (close_time <= clôture de la barre de base), -1 sinon."""
    ct = htf["close_time"].to_numpy("datetime64[ns]").astype("int64")
    return np.searchsorted(ct, base_close_ns, side="right") - 1


def quality_report(df: pd.DataFrame, name: str) -> dict:
    spec = SPECS.get(name)
    idx = df.index
    step = int(np.median(np.diff(ns(idx))) // 60_000_000_000) if len(idx) > 2 else 5
    d = np.diff(ns(idx)) // 60_000_000_000
    gaps = d[d > step * 3]
    wk = gaps[gaps > 36 * 60]
    bad_ohlc = int(((df.high < df[["open", "close"]].max(axis=1) - 1e-12) | (df.low > df[["open", "close"]].min(axis=1) + 1e-12)).sum())
    ret = np.log(df.close).diff().abs()
    robust = ret.rolling(2000, min_periods=200).median() * 1.4826
    outl = int((ret > 12 * robust.clip(lower=1e-9)).sum())
    h = idx.tz_convert(spec.tz).hour if spec else idx.hour
    dst_ok = None
    if spec and spec.tz != "UTC":
        loc = idx.tz_convert(spec.tz)
        # test heures d'été/hiver : l'heure locale de la plus forte activité doit rester stable
        act = pd.Series(df.volume.to_numpy(), index=loc).groupby([loc.year, loc.month > 6]).apply(
            lambda s: s.groupby(s.index.hour).sum().idxmax() if s.sum() > 0 else -1)
        dst_ok = bool(act.nunique() <= 2)
    years = (idx[-1] - idx[0]).days / 365.25
    return {"instrument": name, "source": df.attrs.get("source", "?"), "bars": len(df),
            "start": str(idx[0]), "end": str(idx[-1]), "years": round(years, 2), "step_min": step,
            "duplicates": int(idx.duplicated().sum()), "monotonic": bool(idx.is_monotonic_increasing),
            "gaps_intraday": int(((gaps > step * 3) & (gaps <= 36 * 60)).sum()), "gaps_weekend": int(len(wk)),
            "bad_ohlc": bad_ohlc, "outlier_bars": outl, "zero_range_pct": round(float((df.high == df.low).mean() * 100), 2),
            "weekend_bars": int(((idx.weekday == 5) | ((idx.weekday == 6) & (idx.hour < 21))).sum()) if (spec and spec.kind != "crypto") else 0,
            "dst_consistent": dst_ok, "synthetic": str(df.attrs.get("source", "")).startswith("SYNTH")}
