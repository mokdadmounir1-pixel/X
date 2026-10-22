"""Scénarios SYNTHÉTIQUES de tables de trades pour mesurer le comportement de la boucle d'évolution :
  - nul        : aucune variante n'a d'avantage -> l'évolution ne doit PAS fabriquer de gain (promotions rares) ;
  - decay      : le champion perd son avantage en cours de route et une autre variante la gagne (changement de régime) ;
  - session    : une zone horaire est perdante (insight valide) ;
  - stable     : un champion robuste, qui ne doit pas être touché.
Chaque trade vaut +3R (proba p) ou −1R ; espérance = 4p−1 ; coût déjà inclus."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .engine import EvolveCfg, evolve_all, summarize
from .journal import EvoJournal

NS_D = 86_400 * 10**9


def make_trades(p_fn, months=48, per_month=14, seed=0, start="2021-01-04", variants=10, syms=("EURUSD", "US500", "XAUUSD"),
                bad_session=None):
    """p_fn(variant_index, month_index) -> probabilité de gain. bad_session : (variant, "london") perd systématiquement."""
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp(start, tz="UTC").value
    n_tot = months * per_month
    out = {}
    for v in range(variants):
        e = np.sort(t0 + rng.integers(0, months * 30 * NS_D, n_tot))
        mi = ((e - t0) // (30 * NS_D)).astype(int)
        hr = (e // (3_600 * 10**9)) % 24
        p = np.array([p_fn(v, m) for m in mi])
        if bad_session is not None and bad_session[0] == v:
            lon = (hr >= 7) & (hr < 12)
            p = np.where(lon, 0.10, p)
        win = rng.random(n_tot) < p
        r = np.where(win, 3.0, -1.0)
        out[f"v{v}@fixed3"] = pd.DataFrame({"sym": rng.choice(syms, n_tot), "entry_t": e, "exit_t": e + 6 * 3_600 * 10**9,
                                            "r": r, "grade": 1, "mae_r": 0.5, "mfe_r": np.where(win, 3.0, 0.5)})
    return {"scenario": out}


SCENARIOS = {
    "nul": lambda v, m: 0.25,
    "stable": lambda v, m: 0.34 if v == 0 else 0.25,
    "decay": lambda v, m: (0.34 if m < 26 else 0.20) if v == 0 else ((0.25 if m < 26 else 0.36) if v == 3 else 0.25),
}


def run_scenario(name, seed=0, cfg: EvolveCfg | None = None, bad_session=None):
    tv = make_trades(SCENARIOS.get(name, SCENARIOS["nul"]), seed=seed, bad_session=bad_session)
    res = evolve_all(tv, cfg or EvolveCfg(seed=seed), EvoJournal(None))
    return res, summarize(res, seed=seed)


def calibrate_evolve(n=20, cfg=None, seed0=0):
    """Taux de promotions et gain moyen par scénario (SYNTHÉTIQUE)."""
    rows = {}
    for name in ("nul", "stable", "decay"):
        gains, promos, rbs, pauses, useful = [], [], [], [], 0
        for s in range(n):
            res, sm = run_scenario(name, seed0 + s, cfg)
            p = sm["_portefeuille"]
            gains.append(p["gain_R_par_mois"])
            promos.append(res["journal"].count("PROMOTION")); rbs.append(res["journal"].count("RETOUR_ARRIERE"))
            pauses.append(res["journal"].count("PAUSE"))
            useful += p["verdict_evolution"].startswith("UTILE")
        rows[name] = {"series": n, "gain_moyen_R_par_mois": round(float(np.mean(gains)), 3),
                      "gain_p5_p95": [round(float(np.percentile(gains, 5)), 3), round(float(np.percentile(gains, 95)), 3)],
                      "promotions_par_serie": round(float(np.mean(promos)), 2), "retours_arriere_par_serie": round(float(np.mean(rbs)), 2),
                      "pauses_par_serie": round(float(np.mean(pauses)), 2), "verdict_UTILE": f"{useful}/{n}"}
    return {"label": "[SYNTHÉTIQUE] tables de trades simulées, pas de marché", "scenarios": rows}
