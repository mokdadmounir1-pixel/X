"""Analyse rétrospective AVEC GARDE-FOUS : partage chronologique purgé, importance par permutation hors-échantillon, test nul par étiquettes mélangées, règles de seuil proposées puis jugées hors-échantillon avec correction du nombre de tests.

Principe : fouiller des milliers de trades trouve TOUJOURS des motifs dans le bruit. Une règle n'est retenue que si elle améliore l'espérance sur la partie la plus RÉCENTE, jamais vue pendant sa recherche, et reste significative après correction de Bonferroni. Aucune règle n'est appliquée au système : elle sort comme PROPOSITION (spec à préenregistrer).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..lab.stats import sign_flip_pvalue
from ..ml.model import auc


def chrono_split(ds: pd.DataFrame, train_frac: float = 0.6, purge_bars: int = 64, gap_days: float = 3.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Les `train_frac` premiers trades (par date d'ENTRÉE) pour apprendre ; un trou (purge) puis le reste pour juger. Les trades du jeu d'apprentissage qui se terminent après le début du test sont retirés."""
    d = ds.sort_values("entry_time").reset_index(drop=True); k = int(len(d) * train_frac); cut = d.loc[k, "entry_time"]
    train = d[(d.index < k) & (d["exit_time"] < cut - pd.Timedelta(days=gap_days))]; test = d[d["entry_time"] >= cut + pd.Timedelta(days=gap_days)]
    return train, test


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, feats: list[str], rounds: int = 150, seed: int = 0):
    import lightgbm as lgb
    p = dict(objective="binary", learning_rate=0.03, num_leaves=7, min_data_in_leaf=50, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0, verbose=-1, seed=seed, num_threads=1, deterministic=True)
    m = lgb.train(p, lgb.Dataset(train[feats], label=train["win"]), num_boost_round=rounds)
    return m, m.predict(test[feats])


def permutation_importance(model, test: pd.DataFrame, feats: list[str], seed: int = 0, repeats: int = 20) -> dict:
    """Baisse moyenne de l'AUC hors-échantillon quand une variable est mélangée (positif = utile). Mesuré sur le TEST, pas sur l'apprentissage."""
    rng = np.random.default_rng(seed); base = auc(test["win"].to_numpy(), model.predict(test[feats])); out = {}
    for f in feats:
        drops = []
        for _ in range(repeats):
            t = test[feats].copy(); t[f] = rng.permutation(t[f].to_numpy()); drops.append(base - auc(test["win"].to_numpy(), model.predict(t)))
        out[f] = float(np.mean(drops))
    return out


def auc_null_p(y: np.ndarray, score: np.ndarray, n: int = 500, seed: int = 0) -> dict:
    """p-valeur de l'AUC observée contre l'AUC d'étiquettes mélangées (même score)."""
    rng = np.random.default_rng(seed); obs = auc(y, score); null = np.array([auc(rng.permutation(y), score) for _ in range(n)])
    return {"auc": float(obs), "null_mean": float(np.nanmean(null)), "p_value": float((1 + np.sum(null >= obs)) / (1 + n))}


def propose_rules(train: pd.DataFrame, test: pd.DataFrame, feats: list[str], quantiles=(0.2, 0.4, 0.6, 0.8), min_keep: float = 0.3, alpha: float = 0.05) -> dict:
    """Règles à un seuil « garder les trades où X >= q » ou « X <= q » : seuil cherché sur le TRAIN (le meilleur par variable), jugé sur le TEST. p-valeur par test de signe sur les R gardés
    puis correction de Bonferroni sur le nombre TOTAL de règles essayées (variables x sens x seuils). Une règle n'est retenue que si elle améliore l'espérance du test ET reste significative."""
    tried, cands = 0, []
    for f in feats:
        x = train[f].to_numpy(float); ok = np.isfinite(x)
        if ok.sum() < 100:
            continue
        for q in quantiles:
            thr = float(np.nanquantile(x, q))
            for sense in (">=", "<="):
                tried += 1; keep = (train[f] >= thr) if sense == ">=" else (train[f] <= thr)
                if keep.mean() < min_keep or keep.sum() < 50:
                    continue
                cands.append((float(train.loc[keep, "r"].mean() - train["r"].mean()), f, thr, sense))
    best = {}
    for gain, f, thr, sense in sorted(cands, reverse=True):
        best.setdefault(f, (gain, thr, sense))
    n_tests = max(len(best), 1); out = []
    for f, (gain, thr, sense) in best.items():
        keep = (test[f] >= thr) if sense == ">=" else (test[f] <= thr); r = test.loc[keep, "r"].to_numpy()
        if len(r) < 30:
            continue
        gain, p = subset_gain_p(test["r"].to_numpy(), np.asarray(keep)); out.append({"feature": f, "rule": f"{f} {sense} {thr:.4g}", "train_gain_r": gain, "test_n": int(len(r)), "test_keep_frac": float(keep.mean()),
                                                      "test_mean_r": float(r.mean()), "test_base_mean_r": float(test["r"].mean()), "test_gain_r": gain, "p_value": p, "p_bonferroni": min(1.0, p * n_tests),
                                                      "retained": bool(gain > 0 and r.mean() > 0 and min(1.0, p * n_tests) <= alpha)})
    return {"rules_tried": tried, "rules_tested_on_holdout": n_tests, "rules": sorted(out, key=lambda r: r["p_bonferroni"])}


def subset_gain_p(r: np.ndarray, keep: np.ndarray, B: int = 999, seed: int = 0) -> tuple[float, float]:
    """(gain, p) : gain = moyenne des R gardés - moyenne des R écartés ; p = part des tirages aléatoires de MÊME taille dont le gain est >= (test de permutation du filtre, pas contre zéro : un marché globalement positif ne rend pas toute règle « significative»)."""
    rng = np.random.default_rng(seed); k = int(keep.sum()); n = len(r)
    if k < 10 or k > n - 10:
        return 0.0, 1.0
    gain = float(r[keep].mean() - r[~keep].mean()); tot = r.sum(); null = np.empty(B)
    for b in range(B):
        idx = rng.choice(n, k, replace=False); m1 = r[idx].sum(); null[b] = m1 / k - (tot - m1) / (n - k)
    return gain, float((1 + np.sum(null >= gain)) / (1 + B))


def kmeans(X: np.ndarray, k: int, seed: int = 0, iters: int = 50) -> np.ndarray:
    rng = np.random.default_rng(seed); C = X[rng.choice(len(X), k, replace=False)]
    for _ in range(iters):
        lab = np.argmin(((X[:, None, :] - C[None]) ** 2).sum(-1), axis=1); newC = np.array([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
        if np.allclose(newC, C):
            break
        C = newC
    return lab


def loser_clusters(ds: pd.DataFrame, feats: list[str], k: int = 4) -> list[dict]:
    """Descriptif : regroupe TOUS les trades (variables standardisées) et donne le taux de pertes de chaque amas, avec l'écart au taux global exprimé en erreurs-types. Un amas « très perdant » parmi k est attendu par hasard : à ne pas traiter comme une règle."""
    X = ds[feats].to_numpy(float); ok = np.isfinite(X).all(axis=1); d = ds[ok]; X = X[ok]; Z = (X - X.mean(0)) / (X.std(0) + 1e-12); lab = kmeans(Z, k); base = float((d["r"] <= 0).mean()); out = []
    for j in range(k):
        m = lab == j; n = int(m.sum())
        if n:
            lr = float((d.loc[m, "r"] <= 0).mean()); se = np.sqrt(base * (1 - base) / n); out.append({"cluster": j, "n": n, "loss_rate": lr, "z_vs_global": float((lr - base) / se) if se > 0 else 0.0, "mean_r": float(d.loc[m, "r"].mean())})
    return out
