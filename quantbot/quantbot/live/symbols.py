"""Noms de symboles propres à CHAQUE courtier : quantbot raisonne en noms canoniques (XAUUSD, EURUSD, USTEC...) ; le courtier peut les appeler GOLD, XAUUSD.a, XAUUSDm, NAS100...

`AliasMT5` enveloppe le module MetaTrader5 et traduit les noms canoniques en noms du courtier dans tous les appels portant un symbole ; le reste du code (flux, synchronisation, simulation) n'a pas à changer.
Le profil du courtier vit dans config/broker_profile.json (écrit par scripts/broker_profile.py). Lecture seule : aucune traduction n'ajoute d'ordre.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

PATTERNS = {
    "XAUUSD": ["XAUUSD", "GOLD", "XAU/USD", "GOLDUSD", "XAUUSD."],
    "XAGUSD": ["XAGUSD", "SILVER", "XAG/USD"],
    "EURUSD": ["EURUSD", "EUR/USD"],
    "USTEC": ["USTEC", "NAS100", "US100", "NDX100", "NASDAQ", "USTECH"],
    "DXY": ["DXY", "USDX", "USDIDX", "DOLLAR"],
}
SUFFIXES = ("", ".a", ".m", ".r", ".pro", ".ecn", ".raw", ".c", "m", "_i", "#", "-ECN", "+")


def candidates(canonical: str) -> list[str]:
    base = PATTERNS.get(canonical.upper(), [canonical.upper()])
    return [b + s for b in base for s in SUFFIXES]


def resolve(mt5: Any, canonical: str, overrides: Optional[dict] = None) -> dict:
    """{'canonical', 'broker', 'status'}. Ordre : surcharge explicite > nom exact > candidats usuels > recherche par motif dans symbols_get. Plusieurs candidats : on garde celui qui est négociable ; sinon on liste."""
    if overrides and canonical in overrides:
        return {"canonical": canonical, "broker": overrides[canonical], "status": "surcharge"}
    names: list[str] = []
    try:
        names = [s.name for s in (mt5.symbols_get() or [])]
    except Exception:
        pass
    upper = {n.upper(): n for n in names}
    for c in candidates(canonical):
        if c.upper() in upper:
            return {"canonical": canonical, "broker": upper[c.upper()], "status": "exact" if c.upper() == canonical.upper() else "alias"}
        if not names and mt5.symbol_info(c) is not None:             # pas de liste disponible : on essaie le nom directement
            return {"canonical": canonical, "broker": c, "status": "exact" if c == canonical else "alias"}
    root = re.sub(r"[^A-Z]", "", canonical.upper())[:3]
    similar = [n for n in names if n.upper().startswith(root)][:10]
    return {"canonical": canonical, "broker": None, "status": "introuvable", "similar": similar}


def load_map(root: Path) -> dict:
    try:
        return json.loads((Path(root) / "config" / "broker_profile.json").read_text(encoding="utf-8")).get("symbol_map", {})
    except (OSError, ValueError):
        return {}


class AliasMT5:
    """Proxy du module MetaTrader5 : traduit les symboles canoniques -> courtier dans les appels de lecture ET dans les requêtes d'ordre (copie de la requête, jamais de mutation de l'original)."""
    _SYMBOL_FIRST = {"symbol_info", "symbol_select", "symbol_info_tick", "copy_rates_from_pos", "copy_rates_range", "copy_rates_from", "copy_ticks_from", "copy_ticks_range",
                     "market_book_add", "market_book_get", "market_book_release", "order_calc_profit", "order_calc_margin"}

    def __init__(self, mt5: Any, mapping: dict) -> None:
        self._m, self._map = mt5, dict(mapping)

    def _tr(self, s):
        return self._map.get(s, s) if isinstance(s, str) else s

    def __getattr__(self, name: str):
        attr = getattr(self._m, name)
        if not callable(attr):
            return attr
        if name in self._SYMBOL_FIRST:
            return lambda s, *a, **k: attr(self._tr(s), *a, **k)
        if name == "positions_get" or name == "orders_get":
            return lambda *a, **k: attr(*a, **{**k, **({"symbol": self._tr(k["symbol"])} if "symbol" in k else {})})
        if name in ("order_check", "order_send"):
            return lambda req, *a, **k: attr({**req, **({"symbol": self._tr(req["symbol"])} if "symbol" in req else {})}, *a, **k)
        return attr


def maybe_alias(mt5: Any, root: Path) -> Any:
    m = load_map(root)
    return AliasMT5(mt5, m) if any(k != v for k, v in m.items()) else mt5
