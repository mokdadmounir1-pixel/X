"""Analyse GAGNANTS CONTRE PERDANTS des versions SMC H4/M15 (avec et sans filtre 3 R), sur la PREMIÈRE moitié chronologique de la période de recherche SEULEMENT.

Descriptif : aucun essai consommé. Sélectionne au plus UN filtre par stratégie parmi six prédéclarés (strategies/smc_filters.py), seuil = médiane de la moitié d'entraînement, si son gain sur l'entraînement est
significatif (test de permutation p < 0,10, >= 60 trades conservés, regroupés sur les 3 instruments). La seconde moitié n'est PAS lue ici. Écrit reports/smc_filters_v1/TRAIN.json.
    python scripts/analyze_smc_filters.py
"""
import json, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.data.mt5 import load_mt5_csv
from quantbot.lab.locked import split_locked
from quantbot.strategies import smc_filters as sf
from quantbot.strategies.build import events_for

SPECS = {"smc_h4": "smc_orig_v1", "smc_h4_free": "smc_free_v1", "smc_m15": "smc_orig_v1", "smc_m15_free": "smc_free_v1"}
INSTR = ("EURUSD", "XAUUSD", "USTEC")


def outcomes(df, evs, hold, cost_frac, reward_risk=3.0):
    """R de chaque signal pris isolément (entrée à l'ouverture suivante, stop prioritaire, cible, sortie temporelle), coûts déduits : sert à comparer des filtres, pas à chiffrer un compte."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close")); out = []
    for e in evs:
        i = df.index.get_loc(e.ts) + 1
        if i >= len(df):
            out.append(np.nan); continue
        long = e.direction == "bullish"; ent = o[i]; dist = (ent - e.stop) if long else (e.stop - ent)
        if dist <= 0:
            out.append(np.nan); continue
        tgt = e.target if e.target is not None else (ent + reward_risk * dist if long else ent - reward_risk * dist); res = None
        for j in range(i, min(i + hold, len(df))):
            hs = (l[j] <= e.stop) if long else (h[j] >= e.stop); ht = (h[j] >= tgt) if long else (l[j] <= tgt)
            if hs: res = -1.0; break
            if ht: res = abs(tgt - ent) / dist; break
        if res is None:
            last = c[min(i + hold, len(df)) - 1]; res = ((last - ent) if long else (ent - last)) / dist
        out.append(res - cost_frac * ent / dist)
    return np.array(out)


def perm_p(r, mask, n=4000, seed=0):
    rng = np.random.default_rng(seed); obs = r[mask].mean() - r.mean(); k = int(mask.sum()); cnt = 0
    for _ in range(n):
        idx = rng.permutation(len(r))[:k]; cnt += (r[idx].mean() - r.mean()) >= obs
    return (cnt + 1) / (n + 1)


def main():
    out = {"split": "première moitié chronologique de la période de recherche de chaque instrument", "strategies": {}}
    for name, spn in SPECS.items():
        spec = json.loads((ROOT / "specs" / f"{spn}.json").read_text(encoding="utf-8")); sc = spec["strategies"][name]; R, F = [], []
        for inst in INSTR:
            full = load_mt5_csv(ROOT / "data" / "real" / f"{inst}_M15.csv"); research, _ = split_locked(full, spec["lock_months"], spec["lock_min_frac"]); mid = research.index[len(research) // 2]
            evs = events_for(name, sc, research); train = [e for e in evs if e.ts < mid]
            ex = spec["costs"][inst]; spread = ex["spread_frac"] if ex.get("spread_frac") is not None else 3e-5
            r = outcomes(research, train, sc["max_hold_bars"], spread + 2 * (ex["fee_rate"] + ex["slippage"]), spec["settings"]["risk"]["reward_risk"]); f = sf.features(research, train)
            for fi, ri in zip(f, r):
                if np.isfinite(ri):
                    fi["inst"] = inst; F.append(fi); R.append(ri)
        R = np.array(R); win = R > 0; res = {"n_train": int(len(R)), "E_all": float(R.mean()), "win_rate": float(win.mean()), "winners_vs_losers": {}, "filters": {}, "chosen": None}
        for k in ("stop_atr", "vol_rel", "ob_atr", "rr", "trend_aligned", "hour"):
            v = np.array([x[k] for x in F], float); ok = np.isfinite(v)
            res["winners_vs_losers"][k] = {"mean_winners": float(v[ok & win].mean()), "mean_losers": float(v[ok & ~win].mean()), "n_w": int((ok & win).sum()), "n_l": int((ok & ~win).sum())}
        best = None
        for fn in sf.FILTERS:
            thr = None
            if fn in ("stop_wide", "stop_narrow"): thr = float(np.nanmedian([x["stop_atr"] for x in F]))
            if fn == "vol_high": thr = float(np.nanmedian([x["vol_rel"] for x in F]))
            if fn == "ob_big": thr = float(np.nanmedian([x["ob_atr"] for x in F]))
            m = sf.keep_mask(F, {"name": fn, "threshold": thr}); kept, rem = R[m], R[~m]
            d = {"threshold": thr, "n_kept": int(m.sum()), "E_kept": float(kept.mean()) if len(kept) else None, "E_removed": float(rem.mean()) if len(rem) else None, "uplift": float(kept.mean() - R.mean()) if len(kept) else None}
            d["perm_p"] = float(perm_p(R, m)) if 0 < m.sum() < len(R) else None; res["filters"][fn] = d
            if m.sum() >= 60 and d["perm_p"] is not None and d["perm_p"] < 0.10 and d["E_removed"] < d["E_kept"] and (best is None or d["uplift"] > best[1]):
                best = (fn, d["uplift"], thr)
        res["chosen"] = None if best is None else {"name": best[0], "threshold": best[2]}; out["strategies"][name] = res
        print(f"{name}: n_train={res['n_train']} E={res['E_all']:+.3f}R win={res['win_rate']:.2f} -> filtre retenu : {res['chosen']}")
        for fn, d in res["filters"].items():
            print(f"   {fn:14s} gardés {d['n_kept']:4d} E_gardés={d['E_kept'] if d['E_kept'] is None else round(d['E_kept'],3)} E_écartés={d['E_removed'] if d['E_removed'] is None else round(d['E_removed'],3)} p={d['perm_p'] if d['perm_p'] is None else round(d['perm_p'],3)}")
    (ROOT / "reports" / "smc_filters_v1").mkdir(parents=True, exist_ok=True); (ROOT / "reports" / "smc_filters_v1" / "TRAIN.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
