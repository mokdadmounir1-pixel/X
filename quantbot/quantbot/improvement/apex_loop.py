"""Boucle d'apprentissage d'APEX PULLBACK : isole les échecs à score ÉLEVÉ causés par une expansion de volatilité et propose une variante resserrée.

La variante n'est JAMAIS promue ici : elle sort sous forme de spec candidate (version N+1) qui doit passer le bac à sable (essai préenregistré, portes inchangées, DSR sur tous les essais).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def vol_expansion_failures(trades: list, events: list, df: pd.DataFrame, atr: np.ndarray, s_high: float = 0.85, expansion: float = 1.5) -> list[dict]:
    """Trades PERDANTS dont le score d'entrée > s_high et dont l'ATR a été multiplié par >= `expansion` entre l'entrée et la sortie."""
    by_ts = {e.ts: e for e in events}; idx = {t: i for i, t in enumerate(df.index)}; out = []
    for t in trades:
        if t.r_nominal >= 0:
            continue
        sig_ts = df.index[max(0, idx.get(t.entry_time, 0) - 1)]               # le signal est émis à la clôture précédant l'entrée
        e = by_ts.get(sig_ts)
        if e is None or e.meta.get("S", 0.0) <= s_high:
            continue
        i0, i1 = idx.get(t.entry_time), idx.get(t.exit_time)
        if i0 is None or i1 is None or not np.isfinite(atr[i0]) or atr[i0] <= 0:
            continue
        ratio = float(np.nanmax(atr[i0:i1 + 1]) / atr[i0])
        if ratio >= expansion:
            out.append({"entry_time": str(t.entry_time), "S": float(e.meta["S"]), "atr_expansion": ratio, "r": float(t.r_nominal)})
    return out


def propose_tighter_vol_filter(failures: list[dict], params: dict, min_failures: int = 5, tighten: float = 0.85) -> Optional[dict]:
    """Hypothèse v(N+1) : resserrer la rampe de volatilité (vol_lo, vol_hi) de 15 %. None si trop peu d'échecs pour conclure."""
    if len(failures) < min_failures:
        return None
    new = {"vol_lo": round(params["vol_lo"] * tighten, 4), "vol_hi": round(params["vol_hi"] * tighten, 4)}
    return {"strategy": "apex_pullback", "evidence": {"n_failures": len(failures), "mean_expansion": float(np.mean([f["atr_expansion"] for f in failures]))},
            "param_overrides": new, "status": "CANDIDATE_NOT_PROMOTED",
            "next_step": "écrire une spec préenregistrée avec ces paramètres, l'exécuter UNE fois (essai compté), comparer Sharpe/espérance hors-échantillon avant toute promotion"}
