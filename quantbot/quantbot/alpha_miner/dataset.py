"""Jeu de données de trades : un vecteur de caractéristiques CAUSALES à la barre du signal + l'issue (R net, MFE, MAE).

Toutes les caractéristiques n'utilisent que des barres <= barre du signal (celle qui précède l'entrée). MFE/MAE (en R) sont des RÉSULTATS observés pendant le trade : ce sont des étiquettes d'analyse, jamais des variables explicatives.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..ml.features import frac_diff_ffd
from ..stat.pairs import ou_half_life
from ..strategies.apex import rsi
from ..strategies.events import atr_series
from ..strategies.mtf_confluence import htf_trend

FEATURES = ["atr_ratio", "ret_5_atr", "ret_20_atr", "rsi", "hour_sin", "hour_cos", "spread_atr", "vol_z", "fd_close", "ou_tstat", "trend_d1", "trend_h4", "trend_h1", "range_atr", "side"]


def feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Caractéristiques de TOUTES les barres (causales), alignées sur df.index ; les trades y puisent à la barre du signal."""
    c = df["close"].to_numpy(float); atr = atr_series(df, 14); atr_l = pd.Series(atr).rolling(100).mean().to_numpy(); s = pd.Series(c)
    f = pd.DataFrame(index=df.index)
    f["atr_ratio"] = atr / atr_l; f["ret_5_atr"] = (s - s.shift(5)).to_numpy() / atr; f["ret_20_atr"] = (s - s.shift(20)).to_numpy() / atr
    f["rsi"] = rsi(c, 14); hr = df.index.hour + df.index.minute / 60.0; f["hour_sin"], f["hour_cos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    f["spread_atr"] = (df["spread"].to_numpy(float) / atr) if "spread" in df.columns else np.nan
    v = df["volume"].astype(float); f["vol_z"] = ((v - v.rolling(100).mean()) / v.rolling(100).std()).to_numpy()
    f["fd_close"] = frac_diff_ffd(np.log(c), 0.4)
    # statistique de réversion (t de la régression de Dickey-Fuller sur 200 barres) : calculée toutes les 8 barres puis propagée (causale)
    t = np.full(len(c), np.nan)
    for i in range(200, len(c), 8):
        r = ou_half_life(c[i - 200:i + 1]); t[i] = r.get("t_stat", np.nan)
    f["ou_tstat"] = pd.Series(t).ffill(limit=7).to_numpy()
    for name, rule, fast, slow in (("trend_d1", "1D", 10, 30), ("trend_h4", "4h", 20, 50), ("trend_h1", "1h", 20, 50)):
        tr = htf_trend(df, rule, fast, slow, 1.5); f[name] = tr["bull"] - tr["bear"]                         # signé : +1 tendance haussière forte, -1 baissière forte
    f["range_atr"] = (df["high"] - df["low"]).to_numpy(float) / atr
    return f.replace([np.inf, -np.inf], np.nan)


def build_dataset(df: pd.DataFrame, trades, strategy: str, feats: pd.DataFrame | None = None) -> pd.DataFrame:
    feats = feat = feats if feats is not None else feature_frame(df); idx = {t: i for i, t in enumerate(df.index)}
    o, h, l = (df[k].to_numpy(float) for k in ("open", "high", "low")); rows = []
    for t in trades:
        i0, i1 = idx.get(t.entry_time), idx.get(t.exit_time)
        if i0 is None or i1 is None or i0 < 1:
            continue
        sig = df.index[i0 - 1]; risk = abs(t.entry - t.stop) if t.stop else float("nan")
        if not np.isfinite(risk) or risk <= 0:
            continue
        sg = 1.0 if t.side == "long" else -1.0; seg = slice(i0, i1 + 1)
        mfe = (np.max(h[seg]) - t.entry if sg > 0 else t.entry - np.min(l[seg])) / risk; mae = (t.entry - np.min(l[seg]) if sg > 0 else np.max(h[seg]) - t.entry) / risk
        row = {k: float(feat.loc[sig, k]) if k != "side" else sg for k in FEATURES}
        row.update({"strategy": strategy, "entry_time": t.entry_time, "exit_time": t.exit_time, "r": float(t.r_nominal), "win": int(t.r_nominal > 0), "mfe_r": float(mfe), "mae_r": float(mae), "bars_held": i1 - i0})
        rows.append(row)
    return pd.DataFrame(rows)
