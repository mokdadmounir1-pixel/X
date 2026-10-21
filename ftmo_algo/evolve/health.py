"""Détection de dégradation : z-score de l'espérance récente contre la référence + CUSUM sur les R."""
from __future__ import annotations
import numpy as np


def assess(r_recent, ref_exp: float, ref_sd: float, min_n=15, z_degrade=1.64, pause_z=2.33, cusum_k=0.5, cusum_h=5.0):
    r = np.asarray(r_recent, float)
    n = len(r)
    if n < min_n:
        return {"state": "INSUFFISANT", "n": n}
    sd = max(float(ref_sd), float(r.std(ddof=1)), 1e-6)
    mean = float(r.mean())
    z = (mean - ref_exp) / (sd / np.sqrt(n))
    s = peak = 0.0
    for x in r:
        s = max(0.0, s + (ref_exp - x) / sd - cusum_k)
        peak = max(peak, s)
    alarm = peak > cusum_h
    if mean < 0 and z < -pause_z:
        st = "PAUSE"
    elif z < -z_degrade or alarm:
        st = "DEGRADE"
    else:
        st = "SAIN"
    return {"state": st, "n": n, "mean_R": round(mean, 3), "ref_R": round(ref_exp, 3), "z": round(float(z), 2),
            "cusum_peak": round(peak, 2)}
