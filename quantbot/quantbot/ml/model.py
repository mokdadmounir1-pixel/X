"""Walk-forward LightGBM : réentraînement périodique sur le passé purgé, prédiction hors-échantillon barre par barre, puis simulation de trades."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .cv import PurgedKFold


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """AUC par rangs (Mann-Whitney). NaN si une seule classe."""
    y = np.asarray(y); pos, neg = (y == 1).sum(), (y == 0).sum()
    if pos == 0 or neg == 0:
        return float("nan")
    ranks = pd.Series(p).rank().to_numpy()
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


@dataclass
class MLParams:
    horizon: int = 8                 # barres : portée de l'étiquette ET durée max de la position
    min_train: int = 6000
    refit_every: int = 1000
    embargo_frac: float = 0.01
    threshold: float = 0.65          # P(hausse) >= seuil -> long ; <= 1-seuil -> short
    stop_atr: float = 1.5
    atr_period: int = 14
    cost_frac: float = 0.0           # coût par côté en fraction du prix (frais + glissement) EN PLUS de la moitié du spread mesuré
    lgb: dict = None
    n_rounds: int = 200
    min_atr_frac: float = 0.0        # 0 = désactivé : ignorer le signal si ATR < frac x médiane glissante (500) de l'ATR (marché figé -> risque quasi nul)
    max_spread_risk: float = 0.0     # 0 = désactivé : ignorer si spread d'entrée > frac x risque

    def lgb_params(self) -> dict:
        base = dict(objective="binary", learning_rate=0.03, num_leaves=15, min_data_in_leaf=100, bagging_fraction=0.8, bagging_freq=1,
                    feature_fraction=0.8, lambda_l2=5.0, verbose=-1, seed=0, num_threads=1, deterministic=True)
        return {**base, **(self.lgb or {})}


def make_labels(close: np.ndarray, h: int) -> tuple[np.ndarray, np.ndarray]:
    """y[i] = 1 si close[i+h] > close[i] ; label_end[i] = i+h. Les h dernières barres n'ont pas d'étiquette (y = -1)."""
    n = len(close); y = np.full(n, -1); y[: n - h] = (close[h:] > close[: n - h]).astype(int)
    return y, np.minimum(np.arange(n) + h, n - 1)


def _fit(lgb, X, y, p):
    return lgb.train(p.lgb_params(), lgb.Dataset(X, label=y), num_boost_round=p.n_rounds)


def walk_forward_proba(X: pd.DataFrame, y: np.ndarray, label_end: np.ndarray, p: MLParams, cv_diag: bool = True) -> tuple[np.ndarray, list[dict]]:
    """P(hausse) hors-échantillon. À chaque refit à la barre s : apprentissage sur i avec label_end[i] < s (purge), test sur [s, s+refit_every[."""
    import lightgbm as lgb
    n = len(X); proba = np.full(n, np.nan); log: list[dict] = []
    valid = (~X.isna().any(axis=1).to_numpy()) & (y >= 0)
    s = p.min_train
    while s < n:
        e = min(n, s + p.refit_every)
        tr = np.flatnonzero(valid & (label_end < s)); te = np.flatnonzero(valid[s:e]) + s
        if len(tr) >= 500 and len(te):
            model = _fit(lgb, X.iloc[tr], y[tr], p)
            proba[te] = model.predict(X.iloc[te])
            rec = {"refit_at": int(s), "n_train": int(len(tr)), "oos_auc": auc(y[te], proba[te])}
            if cv_diag:
                cvs = []
                for a, b in PurgedKFold(4, p.embargo_frac).split(label_end[tr]):
                    m = _fit(lgb, X.iloc[tr[a]], y[tr[a]], p)
                    cvs.append(auc(y[tr[b]], m.predict(X.iloc[tr[b]])))
                rec["purged_cv_auc"] = float(np.nanmean(cvs))
            log.append(rec)
        s = e
    return proba, log


def simulate(df: pd.DataFrame, proba: np.ndarray, p: MLParams) -> list[dict]:
    """Signal à la clôture de i, entrée à l'ouverture de i+1, stop = stop_atr x ATR (priorité au stop, gap exécuté à l'ouverture), sortie horaire à l'ouverture de i+1+h. Une seule position."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close")); n = len(df)
    sp = df["spread"].to_numpy(float) if "spread" in df else np.zeros(n)
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.r_[c[0], c[:-1]]), np.abs(l - np.r_[c[0], c[:-1]])))
    atr = pd.Series(tr).ewm(alpha=1 / p.atr_period, adjust=False).mean().to_numpy()
    atr_med = pd.Series(atr).rolling(500, min_periods=100).median().to_numpy()
    trades, i = [], 0
    while i < n - p.horizon - 2:
        pr = proba[i]
        if not np.isnan(pr) and (pr >= p.threshold or pr <= 1 - p.threshold) and not np.isnan(atr[i]) and not _degenerate(p, atr, atr_med, sp, i):
            side = 1 if pr >= p.threshold else -1; ent = i + 1
            risk = p.stop_atr * atr[i]; entry = o[ent] + side * (sp[ent] / 2 + p.cost_frac * o[ent]); stop = entry - side * risk
            exit_i, exit_px, reason = ent + p.horizon, None, "time"
            for j in range(ent, ent + p.horizon):
                if side == 1 and o[j] <= stop or side == -1 and o[j] >= stop:
                    exit_i, exit_px, reason = j, o[j], "stop"; break
                if side == 1 and l[j] <= stop or side == -1 and h[j] >= stop:
                    exit_i, exit_px, reason = j, stop, "stop"; break
            if exit_px is None:
                exit_px = o[exit_i]
            exit_px -= side * (sp[exit_i] / 2 + p.cost_frac * exit_px)
            trades.append({"entry_i": int(ent), "exit_i": int(exit_i), "side": side, "reason": reason, "r": float(side * (exit_px - entry) / risk), "p": float(pr)})
            i = exit_i
        else:
            i += 1
    return trades


def _degenerate(p: MLParams, atr, atr_med, sp, i: int) -> bool:
    if p.min_atr_frac > 0 and (np.isnan(atr_med[i]) or atr[i] < p.min_atr_frac * atr_med[i]):
        return True
    return bool(p.max_spread_risk > 0 and sp[i + 1] > p.max_spread_risk * p.stop_atr * atr[i])
