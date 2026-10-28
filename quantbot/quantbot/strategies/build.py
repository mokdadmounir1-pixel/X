"""Construction des événements d'une stratégie à règles explicites depuis sa définition de spec (partagé par l'interface ; les scripts ont leur copie)."""
from __future__ import annotations

import pandas as pd

from . import amd, apex, cot_extremes, cta_donchian, fixing_seasonality, fvg, goldq, il_svr, kalman_ou, level_proximity, macro_tips, mtf_confluence, ofi_depth, orderflow_iceberg, stop_hunt_engine, orb, smc, vwap

_TWELVE = {"kalman_ou": kalman_ou, "orderflow_iceberg": orderflow_iceberg, "fixing_seasonality": fixing_seasonality, "cot_extremes": cot_extremes, "macro_tips": macro_tips, "ofi_depth": ofi_depth}


def events_for(name: str, scfg: dict, df: pd.DataFrame) -> list:
    if name == "amd":
        return amd.events(df, {**amd.PARAMS, **{k: tuple(v) if isinstance(v, list) else v for k, v in scfg["params"].items()}})
    if name == "vwap":
        return vwap.events(df, scfg["params"])
    if name == "orb":
        return orb.events(df, scfg["params"])
    if name == "cta_donchian":
        return cta_donchian.events(df, scfg.get("params"))
    if name == "omega":
        return omega_events(df, scfg)
    if name in _TWELVE:
        return _TWELVE[name].events(df, scfg.get("params"))
    if name == "il_svr":
        return il_svr.events(df, scfg.get("params"))
    if name == "mtf_confluence":
        return mtf_confluence.events(df, scfg.get("params"))
    if name == "apex_levels":
        return level_proximity.events(df, scfg.get("params"))
    if name.split("__")[0] == "stop_hunt":          # « stop_hunt__sell » / « stop_hunt__flip » : variantes (paramètre mode dans la spec)
        return stop_hunt_engine.events(df, scfg.get("params"))
    if name == "apex_pullback":
        return apex.events(df, scfg.get("params"))
    if name.split("__")[0] in goldq.GENERATORS:          # « gq_zrev__s2 » = variante de paramètres de gq_zrev (spec)
        return goldq.events(df, name.split("__")[0], scfg.get("params"))
    if name.startswith("smc"):
        return smc.events(df, scfg["rule"], scfg["params"])
    return fvg.events(df, scfg["rule"], scfg["params"])


def omega_events(df: pd.DataFrame, scfg: dict) -> list:
    """OMEGA : panier FIGÉ de stratégies membres (définies dans la spec, paramètres identiques à leurs specs d'origine). Les événements des membres sont fusionnés dans l'ordre du temps ;
    deux événements de même sens à moins de `cooldown` barres = une seule idée (le premier est gardé) ; deux sens opposés sur la même barre = conflit, les deux sont écartés.
    Aucune pondération apprise, aucune sélection a posteriori des paramètres : un membre ne change que par une nouvelle spec préenregistrée."""
    p = scfg.get("params") or {}; cooldown = int(p.get("cooldown", 4)); step = df.index.to_series().diff().median() or pd.Timedelta(minutes=15)
    ev = []
    for mname, mcfg in scfg["members"].items():
        for e in events_for(mname, mcfg, df):
            e.meta = {**e.meta, "member": mname}; ev.append(e)
    ev.sort(key=lambda e: (e.ts, e.direction))
    by_ts: dict = {}
    for e in ev:
        by_ts.setdefault(e.ts, set()).add(e.direction)
    out, last = [], {}
    for e in ev:
        if len(by_ts[e.ts]) > 1:
            continue
        prev = last.get(e.direction)
        if prev is not None and e.ts - prev < step * cooldown:
            continue
        last[e.direction] = e.ts; out.append(e)
    return out


# Identifiant lisible et STABLE de chaque stratégie (affiché dans l'attribution des trades)
STRATEGY_CODES = {"amd": "AMD_PO3_M15", "vwap": "VWAP_BAND_M15", "orb": "ORB_15M_PULLBACK", "fvg_h1": "FVG_MIT_1H", "fvg_h4": "FVG_MIT_4H",
                  "smc_h1": "SMC_OB_FVG_1H", "smc_h4": "SMC_OB_FVG_4H",
                  "apex_pullback": "APEX_PULLBACK_ALPHA", "stop_hunt": "XAU_STOP_HUNT", "apex_levels": "APEX_LEVELS_ALPHA", "mtf_confluence": "MTF_TOPDOWN_CONFLUENCE", "il_svr": "IL_SVR_INDEX", "cta_donchian": "CTA_DONCHIAN_H4", "omega": "OMEGA_TRIO", "kalman_ou": "KALMAN_OU_REVERT", "orderflow_iceberg": "ICEBERG_ABSORPTION", "fixing_seasonality": "LONDON_FIX_SEASONAL", "cot_extremes": "COT_EXTREMES", "macro_tips": "MACRO_TIPS_GOLD", "ofi_depth": "OFI_DEPTH_L2", "gq_sweep": "XAU_LIQ_SWEEP", "gq_asia_break": "XAU_ASIA_BREAK", "gq_ema_pull": "XAU_EMA_PULL", "gq_squeeze": "XAU_SQUEEZE", "gq_zrev": "XAU_ZREV"}


def strategy_code(strategy_id: str) -> str:
    base, _, variant = strategy_id.partition("__")
    code = STRATEGY_CODES.get(base, base.upper())
    return f"{code}_{variant.upper()}" if variant and base in STRATEGY_CODES and strategy_id not in STRATEGY_CODES else STRATEGY_CODES.get(strategy_id, code)
