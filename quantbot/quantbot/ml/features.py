"""Features strictement causales (la valeur à la barre t n'utilise que les barres <= t)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ffd_weights(d: float, thresh: float = 1e-4, max_width: int = 2000) -> np.ndarray:
    """Poids de la différenciation fractionnaire à fenêtre fixe (FFD). w_0 = 1, w_k = -w_{k-1} (d-k+1)/k, tronqué quand |w_k| < thresh."""
    w = [1.0]
    for k in range(1, max_width):
        w_k = -w[-1] * (d - k + 1) / k
        if abs(w_k) < thresh:
            break
        w.append(w_k)
    return np.array(w)


def frac_diff_ffd(x: np.ndarray, d: float, thresh: float = 1e-4) -> np.ndarray:
    """Série fractionnairement différenciée ; les (largeur-1) premières valeurs sont NaN (pas de remplissage)."""
    x = np.asarray(x, float); w = ffd_weights(d, thresh); width = len(w)
    out = np.full(len(x), np.nan)
    if len(x) >= width:
        out[width - 1:] = np.convolve(x, w, mode="valid")        # w[0] s'applique à x_t, w[k] à x_{t-k} : conv avec w renversé implicite par 'valid'
    return out


def garman_klass(o, h, l, c, window: int = 20) -> np.ndarray:
    o, h, l, c = (np.asarray(v, float) for v in (o, h, l, c))
    v = 0.5 * np.log(h / l) ** 2 - (2 * np.log(2) - 1) * np.log(c / o) ** 2
    return np.sqrt(np.maximum(pd.Series(v).rolling(window).mean().to_numpy(), 0.0))


def rolling_entropy(ret: np.ndarray, window: int = 100, word: int = 3) -> np.ndarray:
    """Entropie de Shannon (en bits) de la distribution des mots de `word` signes de rendement sur `window` barres. Max = `word` bits."""
    r = np.asarray(ret, float); s = (r > 0).astype(int); n = len(s); k = 2 ** word
    code = np.full(n, -1)
    if n >= word:
        code[word - 1:] = sum(s[word - 1 - j: n - j] << j for j in range(word))
    code[np.isnan(r)] = -1
    code = np.where(pd.Series(np.isnan(r)).rolling(word, min_periods=1).max().to_numpy() > 0, -1, code)
    out = np.full(n, np.nan)
    cum = np.zeros((k, n + 1))
    for sym in range(k):
        cum[sym, 1:] = np.cumsum(code == sym)
    for i in range(window + word, n):
        cnt = cum[:, i + 1] - cum[:, i + 1 - window]
        p = cnt[cnt > 0] / cnt.sum()
        out[i] = -(p * np.log2(p)).sum()
    return out


def amihud(ret, close, volume, window: int = 50) -> np.ndarray:
    ill = np.abs(np.asarray(ret, float)) / np.maximum(np.asarray(close, float) * np.asarray(volume, float), 1e-12)
    return pd.Series(ill).rolling(window).mean().to_numpy()


def build_features(df: pd.DataFrame, d: float = 0.4, fd_thresh: float = 1e-4) -> pd.DataFrame:
    """Matrice de features alignée sur df.index. Les lignes incomplètes (NaN) restent NaN : l'appelant les écarte."""
    c = df["close"].to_numpy(float); lc = np.log(c)
    ret1 = np.r_[np.nan, np.diff(lc)]
    f = pd.DataFrame(index=df.index)
    f["fd_close"] = frac_diff_ffd(lc, d, fd_thresh)
    f["ret_1"] = ret1
    f["ret_5"] = pd.Series(lc).diff(5).to_numpy(); f["ret_20"] = pd.Series(lc).diff(20).to_numpy()
    f["gk_vol"] = garman_klass(df.open, df.high, df.low, df.close, 20)
    f["gk_ratio"] = f["gk_vol"] / pd.Series(f["gk_vol"].to_numpy()).rolling(200).mean().to_numpy()
    f["entropy"] = rolling_entropy(ret1, 100, 3)
    f["amihud"] = amihud(ret1, c, df["volume"].to_numpy(float), 50)
    vol = df["volume"].astype(float)
    f["vol_z"] = ((vol - vol.rolling(100).mean()) / vol.rolling(100).std()).to_numpy()
    hr = df.index.hour + df.index.minute / 60.0
    f["hour_sin"], f["hour_cos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    return f.replace([np.inf, -np.inf], np.nan)
