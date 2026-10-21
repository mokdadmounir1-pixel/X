"""Faisabilité des coûts : à l'échelle M1 le frottement domine. Pour chaque instrument et fenêtre horaire : coût aller-retour
(spread + 2 slippages + commission) rapporté à l'ATR M1 et à la distance de stop ; taux de réussite d'équilibre selon le RR.
Formule : avec c = coût / distance de stop (en R), E = p·(RR+1) − (1+c)  =>  p* = (1+c)/(RR+1)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from ..instruments import SPECS, value_per_unit
from ..indicators import atr_arr

WINDOWS = {"asie 00-07": (0, 7), "londres 07-11": (7, 11), "milieu 11-12.5": (11, 12.5), "new_york 12.5-16.5": (12.5, 16.5),
           "après-midi 16.5-21": (16.5, 21), "nuit 21-24": (21, 24)}


def cost_report(dfs: dict, stop_atr=(1.0, 2.0), rrs=(1.0, 1.5, 2.0, 3.0)) -> dict:
    out = {}
    for sym, d in dfs.items():
        spec = SPECS[sym]
        step = int(np.median(np.diff(d.index.asi8)) // 60_000_000_000)
        atr = atr_arr(d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float), 30)
        spr = d["spread"].to_numpy(float) if "spread" in d and np.isfinite(d["spread"]).any() else np.full(len(d), spec.spread)
        value = value_per_unit(spec, float(d.close.median()))
        rt = spr + 2 * spec.slippage + spec.commission_lot / value
        hr = d.index.hour.to_numpy() + d.index.minute.to_numpy() / 60
        rows = {}
        for w, (a, b) in WINDOWS.items():
            m = (hr >= a) & (hr < b) & (np.arange(len(d)) > 300)
            if m.sum() < 100:
                continue
            medatr, medrt = float(np.median(atr[m])), float(np.median(rt[m]))
            row = {"atr_moyen_prix": round(medatr, 6), "cout_AR_prix": round(medrt, 6), "cout_sur_ATR": round(medrt / medatr, 3)}
            for k in stop_atr:
                c = medrt / (k * medatr)
                row[f"stop={k}ATR"] = {"cout_R": round(c, 3),
                                       "winrate_equilibre": {f"RR{r}": round((1 + c) / (r + 1), 3) for r in rrs},
                                       "joue": bool(c <= 0.25)}
            rows[w] = row
        out[sym] = {"pas_min": step, "source_spread": "colonne spread des barres" if "spread" in d else "spec [HYPOTHÈSE]",
                    "fenetres": rows}
    return out


def print_costs(rep: dict, label: str):
    print(f"\n=== FAISABILITÉ DES COÛTS {label} ===  (cout_R ≤ 0,25 requis pour jouer ; WR* = taux de réussite d'équilibre)")
    for sym, r in rep.items():
        print(f"-- {sym} (spread : {r['source_spread']})")
        for w, row in r["fenetres"].items():
            s1, s2 = row["stop=1.0ATR"], row["stop=2.0ATR"]
            print(f"   {w:20s} coût/ATR {row['cout_sur_ATR']:.2f} | stop 1 ATR : {s1['cout_R']:.2f} R, WR* RR2 {s1['winrate_equilibre']['RR2.0']:.2f}"
                  f" {'OK' if s1['joue'] else '--'} | stop 2 ATR : {s2['cout_R']:.2f} R, WR* RR2 {s2['winrate_equilibre']['RR2.0']:.2f} {'OK' if s2['joue'] else '--'}")
