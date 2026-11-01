"""Construction des événements d'une stratégie à règles explicites depuis sa définition de spec (partagé par l'interface ; les scripts ont leur copie)."""
from __future__ import annotations

import pandas as pd

from . import amd, apex, ibs_rsi2_trend, noise_area, gap_fade, ibs_reversion, london_breakout, orb_stocks_in_play, rsi2_reversion, turn_of_month, intraday_momentum, overnight_premium, cot_extremes, cta_donchian, fixing_seasonality, fvg, goldq, il_svr, kalman_ou, level_proximity, macro_tips, mtf_confluence, ofi_depth, orderflow_iceberg, stop_hunt_engine, orb, smc, vwap

_TWELVE = {"ibs_rsi2_trend": ibs_rsi2_trend, "noise_area": noise_area, "gap_fade": gap_fade, "ibs_reversion": ibs_reversion, "rsi2_reversion": rsi2_reversion, "turn_of_month": turn_of_month, "london_breakout": london_breakout, "orb_stocks_in_play": orb_stocks_in_play, "overnight_premium": overnight_premium, "intraday_momentum": intraday_momentum, "kalman_ou": kalman_ou, "orderflow_iceberg": orderflow_iceberg, "fixing_seasonality": fixing_seasonality, "cot_extremes": cot_extremes, "macro_tips": macro_tips, "ofi_depth": ofi_depth}


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
    if name.split("__")[0] in _TWELVE:             # « ibs_rsi2_trend__de » = variante (autre marché) de la même stratégie
        return _TWELVE[name.split("__")[0]].events(df, scfg.get("params"))
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
    """OMEGA : algorithme de CONFLUENCE de trois stratégies membres FIGÉES (définies dans la spec, paramètres identiques à leurs specs d'origine). Rien n'est appris.

    À chaque événement d'un membre, à l'instant t (jamais d'information postérieure) : accord = nombre de membres DISTINCTS ayant émis le même sens dans les `window` dernières barres (t compris),
    opposition = nombre de membres distincts ayant émis le sens contraire dans la même fenêtre ; net = accord - opposition. net < 1 : écarté (les membres se contredisent).
    Confiance = base + pas x (net - 1) : 1 membre = prudent (petite taille), 2 d'accord = standard, 3 d'accord = pleine taille ; la confiance pilote la taille via le dimensionnement par score existant.
    Même sens à moins de `cooldown` barres du dernier événement retenu : une seule idée. Stop et cible = ceux du membre qui déclenche. mode « union » : fusion simple sans confluence (version 1)."""
    p = scfg.get("params") or {}; cooldown = int(p.get("cooldown", 4)); window = int(p.get("window", 8)); mode = p.get("mode", "confluence")
    base, step_c = float(p.get("conf_base", 0.55)), float(p.get("conf_step", 0.20))
    bar = df.index.to_series().diff().median(); bar = bar if pd.notna(bar) else pd.Timedelta(minutes=15)
    ev = []
    for mname, mcfg in scfg["members"].items():
        for e in events_for(mname, mcfg, df):
            e.meta = {**e.meta, "member": mname}; ev.append(e)
    ev.sort(key=lambda e: (e.ts, e.meta["member"]))
    by_ts: dict = {}
    for e in ev:
        by_ts.setdefault(e.ts, set()).add(e.direction)
    out, last, seen = [], {}, []
    for e in ev:
        seen.append(e); lo = e.ts - bar * window
        if mode == "union":
            if len(by_ts[e.ts]) > 1:
                continue
            net = 1
        else:
            recent = [x for x in seen if x.ts > lo]
            net = len({x.meta["member"] for x in recent if x.direction == e.direction}) - len({x.meta["member"] for x in recent if x.direction != e.direction})
            if net < 1:
                continue
        prev = last.get(e.direction)
        if prev is not None and e.ts - prev < bar * cooldown:
            continue
        last[e.direction] = e.ts
        e.meta = {**e.meta, "confidence": min(0.95, base + step_c * (net - 1)), "omega_net": net}; out.append(e)
    return out


def exit_rule_for(name: str, scfg: dict):
    """Règle de sortie propre à une stratégie (callable (df, position) -> raison ou None), ou None : les stratégies sans règle gardent stop / cible / durée comme avant."""
    mod = _TWELVE.get(name.split("__")[0])
    return mod.exit_rule(scfg.get("params")) if mod is not None and hasattr(mod, "exit_rule") else None


# Identifiant lisible et STABLE de chaque stratégie (affiché dans l'attribution des trades)
STRATEGY_CODES = {"amd": "AMD_PO3_M15", "vwap": "VWAP_BAND_M15", "orb": "ORB_15M_PULLBACK", "fvg_h1": "FVG_MIT_1H", "fvg_h4": "FVG_MIT_4H",
                  "smc_h1": "SMC_OB_FVG_1H", "smc_h4": "SMC_OB_FVG_4H", "smc_m15": "SMC_OB_FVG_15M", "smc_h1_free": "SMC_OB_FVG_1H_FREE", "smc_h4_free": "SMC_OB_FVG_4H_FREE", "smc_m15_free": "SMC_OB_FVG_15M_FREE",
                  "apex_pullback": "APEX_PULLBACK_ALPHA", "stop_hunt": "XAU_STOP_HUNT", "apex_levels": "APEX_LEVELS_ALPHA", "mtf_confluence": "MTF_TOPDOWN_CONFLUENCE", "il_svr": "IL_SVR_INDEX", "cta_donchian": "CTA_DONCHIAN_H4", "omega": "OMEGA_TRIO", "ibs_rsi2_trend": "IBS_RSI2_TREND", "noise_area": "NOISE_AREA", "gap_fade": "GAP_FADE_INDEX", "ibs_reversion": "IBS_REVERSION_INDEX", "rsi2_reversion": "RSI2_REVERSION_INDEX", "turn_of_month": "TURN_OF_MONTH_INDEX", "london_breakout": "LONDON_BREAKOUT", "orb_stocks_in_play": "ORB_STOCKS_IN_PLAY", "overnight_premium": "OVERNIGHT_PREMIUM", "intraday_momentum": "INTRADAY_MOMENTUM", "kalman_ou": "KALMAN_OU_REVERT", "orderflow_iceberg": "ICEBERG_ABSORPTION", "fixing_seasonality": "LONDON_FIX_SEASONAL", "cot_extremes": "COT_EXTREMES", "macro_tips": "MACRO_TIPS_GOLD", "ofi_depth": "OFI_DEPTH_L2", "gq_sweep": "XAU_LIQ_SWEEP", "gq_asia_break": "XAU_ASIA_BREAK", "gq_ema_pull": "XAU_EMA_PULL", "gq_squeeze": "XAU_SQUEEZE", "gq_zrev": "XAU_ZREV"}


def strategy_code(strategy_id: str) -> str:
    base, _, variant = strategy_id.partition("__")
    code = STRATEGY_CODES.get(base, base.upper())
    return f"{code}_{variant.upper()}" if variant and base in STRATEGY_CODES and strategy_id not in STRATEGY_CODES else STRATEGY_CODES.get(strategy_id, code)
