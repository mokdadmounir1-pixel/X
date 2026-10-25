"""Construction des réglages d'une spec préenregistrée (partagée par les scripts et l'interface)."""
from __future__ import annotations

from ..config import Settings
from ..data.mt5 import leverage_cap_from_gaps


def build_settings(spec: dict, name: str, costs_measured: dict, research=None) -> Settings:
    c = spec["costs"][name]
    spread = c["spread_frac"] if c.get("spread_frac") is not None else costs_measured["spread_frac"]
    if spread is None:
        raise SystemExit(f"{name}: aucun spread fiable ni hypothèse déclarée : refus (un coût nul n'est jamais supposé)")
    base = spec["settings"]
    base = {**base, "execution": {**base.get("execution", {}), "fee_rate": c["fee_rate"],
                                  "slippage": c["slippage"], "spread": spread}}
    rule = spec.get("leverage_rule")
    if rule and research is not None:  # plafond de levier dérivé des gaps de la période de RECHERCHE uniquement
        lev = leverage_cap_from_gaps(research, rule["loss_budget"], rule["quantile"], rule["min"], rule["max"])
        base = {**base, "risk": {**base.get("risk", {}), "max_leverage": lev}}
    return Settings.from_dict(base)
