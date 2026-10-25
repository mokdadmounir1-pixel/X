"""Construction des événements d'une stratégie à règles explicites depuis sa définition de spec (partagé par l'interface ; les scripts ont leur copie)."""
from __future__ import annotations

import pandas as pd

from . import amd, fvg, goldq, orb, smc, vwap


def events_for(name: str, scfg: dict, df: pd.DataFrame) -> list:
    if name == "amd":
        return amd.events(df, {**amd.PARAMS, **{k: tuple(v) if isinstance(v, list) else v for k, v in scfg["params"].items()}})
    if name == "vwap":
        return vwap.events(df, scfg["params"])
    if name == "orb":
        return orb.events(df, scfg["params"])
    if name in goldq.GENERATORS:
        return goldq.events(df, name, scfg.get("params"))
    if name.startswith("smc"):
        return smc.events(df, scfg["rule"], scfg["params"])
    return fvg.events(df, scfg["rule"], scfg["params"])


# Identifiant lisible et STABLE de chaque stratégie (affiché dans l'attribution des trades)
STRATEGY_CODES = {"amd": "AMD_PO3_M15", "vwap": "VWAP_BAND_M15", "orb": "ORB_15M_PULLBACK", "fvg_h1": "FVG_MIT_1H", "fvg_h4": "FVG_MIT_4H",
                  "smc_h1": "SMC_OB_FVG_1H", "smc_h4": "SMC_OB_FVG_4H",
                  "gq_sweep": "XAU_LIQ_SWEEP", "gq_asia_break": "XAU_ASIA_BREAK", "gq_ema_pull": "XAU_EMA_PULL", "gq_squeeze": "XAU_SQUEEZE", "gq_zrev": "XAU_ZREV"}


def strategy_code(strategy_id: str) -> str:
    return STRATEGY_CODES.get(strategy_id, strategy_id.upper())
