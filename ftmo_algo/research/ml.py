"""Filtre ML walk-forward : régression logistique L2 (numpy pur, pas de dépendance), labels triple-barrière
(stop / cible RR / stop temporel via la simulation), purge + embargo. Ne GÉNÈRE aucun trade : il FILTRE les
candidats des autres algos."""
from __future__ import annotations
import numpy as np
import pandas as pd


class Logit:
    def __init__(self, l2=1.0, iters=60):
        self.l2, self.iters = l2, iters

    def fit(self, X, y):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = np.c_[np.ones(len(X)), (X - self.mu) / self.sd]
        w = np.zeros(Z.shape[1]); R = np.eye(Z.shape[1]) * self.l2; R[0, 0] = 0
        for _ in range(self.iters):          # Newton-Raphson (IRLS)
            p = 1 / (1 + np.exp(-np.clip(Z @ w, -30, 30)))
            g = Z.T @ (p - y) + R @ w
            H = (Z * (p * (1 - p))[:, None]).T @ Z + R + 1e-6 * np.eye(len(w))
            step = np.linalg.solve(H, g)
            w -= step
            if np.abs(step).max() < 1e-6:
                break
        self.w = w
        return self

    def predict(self, X):
        Z = np.c_[np.ones(len(X)), (X - self.mu) / self.sd]
        return 1 / (1 + np.exp(-np.clip(Z @ self.w, -30, 30)))


def design(cands: pd.DataFrame, algos: list[str]) -> np.ndarray:
    F = np.stack(cands["feat"].to_numpy()).astype("float64")
    oh = np.stack([(cands["algo"] == a).to_numpy() for a in algos], 1).astype("float64")
    return np.c_[F, oh, cands["grade"].to_numpy()[:, None].astype("float64")]


def ml_filter(cands: pd.DataFrame, folds, algos, embargo_days=5, min_train=120, margin=0.05, l2=3.0):
    """Retourne (trades OOS filtrés, trades OOS candidats, détails par pli). `margin` fixé a priori."""
    emb = embargo_days * 86_400 * 10**9
    kept, allc, info = [], [], []
    X = design(cands, algos) if len(cands) else np.zeros((0, 1))
    y = (cands["r"].to_numpy() > 0).astype(float) if len(cands) else np.zeros(0)
    et, xt = (cands["entry_t"].to_numpy(), cands["exit_t"].to_numpy()) if len(cands) else (np.zeros(0), np.zeros(0))
    for i, f in enumerate(folds):
        tr = (et >= f.train_start) & (xt < f.test_start - emb)       # purge : sorties avant le test - embargo
        te = (et >= f.test_start) & (et < f.test_end)
        allc.append(cands[te].assign(fold=i))
        if tr.sum() < min_train or te.sum() == 0:
            info.append({"fold": i, "status": "pas assez de données d'entraînement", "train_n": int(tr.sum())})
            continue
        m = Logit(l2).fit(X[tr], y[tr])
        p = m.predict(X[te])
        thr = float(y[tr].mean() + margin)
        sel = p >= thr
        kept.append(cands[te][sel].assign(fold=i, variant="ml@logit"))
        info.append({"fold": i, "status": "ok", "train_n": int(tr.sum()), "thr": round(thr, 3),
                     "kept": int(sel.sum()), "of": int(te.sum())})
    cat = lambda L: pd.concat(L, ignore_index=True) if L else cands.iloc[0:0].assign(fold=[], variant=[])
    return cat(kept), cat(allc), info
