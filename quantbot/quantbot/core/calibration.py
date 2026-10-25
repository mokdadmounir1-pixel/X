"""Calibration score -> espérance nette (en R nominal) par régression isotone (PAV).

Pourquoi isotone : un seul paramètre libre par courbe (la monotonie), pas de forme imposée, aucune fuite
possible vers l'avenir. Le score n'est PAS une probabilité : cette courbe est ce qui lui donne un sens.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..lab.registry import canonical_hash


def isotonic_fit(x, y, w=None):
    """Régression isotone croissante (PAV). Retourne (x_uniques triés, valeurs ajustées par x_unique)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    w = np.ones_like(y) if w is None else np.asarray(w, float)
    order = np.argsort(x, kind="mergesort")
    x, y, w = x[order], y[order], w[order]
    ux, inv = np.unique(x, return_inverse=True)
    sw = np.bincount(inv, weights=w)
    sy = np.bincount(inv, weights=w * y) / sw
    vals, wts, counts = [], [], []
    for v, wt in zip(sy, sw):
        vals.append(v); wts.append(wt); counts.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v2, w2, c2 = vals.pop(), wts.pop(), counts.pop()
            vals[-1] = (vals[-1] * wts[-1] + v2 * w2) / (wts[-1] + w2)
            wts[-1] += w2
            counts[-1] += c2
    fitted = np.repeat(vals, counts)
    return ux, fitted


@dataclass
class Curve:
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    n_train: int = 0
    min_score: float = 0.0  # en dessous : « pas de setup », jamais d'extrapolation

    def predict(self, s: float) -> Optional[float]:
        if not self.x or s < self.min_score:
            return None
        return float(np.interp(s, self.x, self.y))

    def predict_many(self, s) -> np.ndarray:
        s = np.asarray(s, float)
        out = np.full(s.shape, np.nan)
        if not self.x:
            return out
        ok = s >= self.min_score
        out[ok] = np.interp(s[ok], self.x, self.y)
        return out


def fit_curve(scores, outcomes, min_score: float, min_support: int, weights=None) -> Curve:
    """Courbe sur les barres où score >= min_score (hors-zone : aucune prédiction)."""
    s, y = np.asarray(scores, float), np.asarray(outcomes, float)
    m = np.isfinite(s) & np.isfinite(y) & (s >= min_score)
    if m.sum() < min_support:
        return Curve(n_train=int(m.sum()), min_score=min_score)
    ux, fitted = isotonic_fit(s[m], y[m], None if weights is None else np.asarray(weights)[m])
    return Curve([float(v) for v in ux], [float(v) for v in fitted], int(m.sum()), min_score)


@dataclass
class CalibrationModel:
    long: Curve
    short: Curve
    margin: float  # espérance minimale (R nominal) exigée pour trader
    meta: dict = field(default_factory=dict)

    def decide(self, bull: float, bear: float) -> Optional[tuple[str, float]]:
        """(direction, espérance calibrée) du meilleur côté dépassant la marge, sinon None."""
        ev_l, ev_s = self.long.predict(bull), self.short.predict(bear)
        cands = [(d, ev) for d, ev in (("bullish", ev_l), ("bearish", ev_s)) if ev is not None and ev > self.margin]
        return max(cands, key=lambda c: c[1]) if cands else None

    def to_dict(self) -> dict:
        return {"long": self.long.__dict__, "short": self.short.__dict__, "margin": self.margin, "meta": self.meta}

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationModel":
        return cls(Curve(**d["long"]), Curve(**d["short"]), d["margin"], d.get("meta", {}))

    def hash(self) -> str:
        return canonical_hash({k: v for k, v in self.to_dict().items() if k != "meta"})

    def save(self, path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1)

    @classmethod
    def load(cls, path) -> "CalibrationModel":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


@dataclass
class StratifiedModel:
    """Une courbe isotone par (côté, état du contexte multi-timeframe) : 6 courbes pour 3 états."""

    curves: dict = field(default_factory=dict)  # "long|1" -> Curve
    margin: float = 0.10
    meta: dict = field(default_factory=dict)

    def decide(self, bull: float, bear: float, state: int):
        ev_l = self.curves.get(f"long|{state}", Curve()).predict(bull)
        ev_s = self.curves.get(f"short|{state}", Curve()).predict(bear)
        cands = [(d, ev) for d, ev in (("bullish", ev_l), ("bearish", ev_s)) if ev is not None and ev > self.margin]
        return max(cands, key=lambda c: c[1]) if cands else None

    def to_dict(self) -> dict:
        return {"curves": {k: c.__dict__ for k, c in sorted(self.curves.items())}, "margin": self.margin, "meta": self.meta}

    @classmethod
    def from_dict(cls, d: dict) -> "StratifiedModel":
        return cls({k: Curve(**v) for k, v in d["curves"].items()}, d["margin"], d.get("meta", {}))

    def hash(self) -> str:
        return canonical_hash({k: v for k, v in self.to_dict().items() if k != "meta"})

    def save(self, path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1)

    @classmethod
    def load(cls, path) -> "StratifiedModel":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


def fit_stratified(bull, bear, long_r, short_r, state, train_mask, zone: float, support: int, margin: float,
                   meta: dict | None = None) -> StratifiedModel:
    model = StratifiedModel(margin=margin, meta=meta or {})
    for st in (-1, 0, 1):
        m = train_mask & (np.asarray(state) == st)
        model.curves[f"long|{st}"] = fit_curve(np.asarray(bull)[m], np.asarray(long_r)[m], zone, support)
        model.curves[f"short|{st}"] = fit_curve(np.asarray(bear)[m], np.asarray(short_r)[m], zone, support)
    return model
