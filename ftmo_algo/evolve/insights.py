"""Où et quand une stratégie gagne ou perd : sessions, jours, instruments, corrélations entre algos, capture du MFE.
Tout test est corrigé pour les comparaisons multiples (Šidák) ; une trouvaille n'est qu'une HYPOTHÈSE tant qu'elle
n'a pas gagné son test en ombre (engine.py). Seules les EXCLUSIONS de zones perdantes sont jamais appliquées."""
from __future__ import annotations
import numpy as np
import pandas as pd

NS_H = 3_600 * 10**9
NS_D = 86_400 * 10**9


def sess_of(hour):
    h = np.asarray(hour)
    return np.where(h < 7, "asia", np.where(h < 12, "london", np.where(h < 17, "ny", "late")))


def prep(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) == 0 or "sess" in df.columns:
        return df
    e = df.entry_t.to_numpy("int64")
    hr = (e // NS_H) % 24
    out = df.copy()
    out["hr"] = hr
    out["sess"] = sess_of(hr)
    out["dow"] = ((e // NS_D) + 3) % 7        # 1970-01-01 = jeudi
    return out


def labels(df):
    return {"sess": df.sess.to_numpy(), "dow": df.dow.to_numpy().astype(str), "sym": df.sym.to_numpy().astype(str)}


def excl_mask(df: pd.DataFrame, excl) -> np.ndarray:
    """True = trade conservé."""
    keep = np.ones(len(df), bool)
    if not excl or len(df) == 0:
        return keep
    lab = labels(df)
    for tag in excl:
        k, v = tag.split(":", 1)
        keep &= lab[k] != v
    return keep


def analyze(df: pd.DataFrame, alpha=0.10, B=999, min_bucket=15, seed=0) -> dict:
    """Moyenne de R par session/jour/instrument contre le reste, test de permutation unilatéral, Šidák."""
    out = {"n": int(len(df)), "buckets": [], "exclude": [], "positive": []}
    if len(df) < 40:
        return out
    df = df.sort_values("entry_t")
    r = df.r.to_numpy("float64")
    half = np.arange(len(r)) < len(r) // 2           # stabilité : la zone doit être perdante dans les DEUX moitiés
    rng = np.random.default_rng(seed)
    lab = labels(df)
    cands = [(k, v, lab[k] == v) for k in lab for v in np.unique(lab[k])]
    cands = [(k, v, m) for k, v, m in cands if min_bucket <= m.sum() <= len(r) - min_bucket]
    if not cands:
        return out
    m_tests = len(cands)
    perms = rng.permuted(np.tile(r, (B, 1)), axis=1)
    a_adj = 1 - (1 - alpha) ** (1 / m_tests)
    for k, v, m in cands:
        obs = float(r[m].mean())
        null = perms[:, m].mean(axis=1)
        p_low = (1 + int((null <= obs).sum())) / (B + 1)
        p_high = (1 + int((null >= obs).sum())) / (B + 1)
        rest = float(r[~m].mean())
        row = {"tag": f"{k}:{v}", "n": int(m.sum()), "mean_R": round(obs, 3), "reste_R": round(rest, 3),
               "p_bas": round(p_low, 4), "p_haut": round(p_high, 4)}
        out["buckets"].append(row)
        h1, h2 = r[m & half], r[m & ~half]
        stable = len(h1) >= 5 and len(h2) >= 5 and h1.mean() < 0 and h2.mean() < 0
        row["stable_2_moities"] = bool(stable)
        if p_low < a_adj and obs < 0 and rest > obs and stable:
            out["exclude"].append(row["tag"])
        if p_high < a_adj and obs > rest:
            out["positive"].append(row["tag"])
    out["m_tests"] = m_tests
    out["alpha_sidak"] = round(a_adj, 5)
    return out


def algo_correlation(tr_by_algo: dict[str, pd.DataFrame]) -> dict:
    """Corrélation des R journaliers entre algos (diversification réelle ou illusoire)."""
    ser = {}
    for a, d in tr_by_algo.items():
        if len(d) < 20:
            continue
        day = pd.to_datetime(d.exit_t.to_numpy("int64"), utc=True).normalize()
        ser[a] = pd.Series(d.r.to_numpy(), index=day).groupby(level=0).sum()
    if len(ser) < 2:
        return {}
    m = pd.DataFrame(ser).fillna(0.0).corr().round(2)
    return {a: {b: float(m.loc[a, b]) for b in m.columns} for a in m.index}


def mfe_capture(df: pd.DataFrame) -> dict:
    """Part du mouvement favorable réellement encaissée (MFE) : indice pour une sortie plus adaptée (HYPOTHÈSE)."""
    if len(df) < 30 or "mfe_r" not in df:
        return {}
    w = df[df.r > 0]
    l = df[df.r <= 0]
    return {"mfe_moyen_R": round(float(df.mfe_r.mean()), 2), "R_moyen": round(float(df.r.mean()), 2),
            "perdants_ayant_atteint_1R": round(float((l.mfe_r >= 1.0).mean()), 3) if len(l) else 0.0,
            "gagnants_mfe_vs_R": round(float((w.mfe_r.mean() - w.r.mean())), 2) if len(w) else 0.0}
