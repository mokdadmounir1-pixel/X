"""Spécifications des instruments. Toutes les valeurs sont des DÉFAUTS [HYPOTHÈSE] à
remplacer par symbol_info() MT5 du courtier réel (voir data.loaders.specs_from_mt5)."""
from __future__ import annotations
from dataclasses import dataclass, field, replace

USDJPY_REF = 150.0  # taux de référence figé pour convertir les P&L JPY (approximation)
USDCAD_REF = 1.37   # idem pour les P&L en CAD (AUDCAD) ; [HYPOTHÈSE] à remplacer par la conversion MT5 réelle


@dataclass(frozen=True)
class Spec:
    name: str
    kind: str                 # fx_usdq | fx_usdb | fx_jpy | index | metal | crypto
    usd_per_unit: float       # USD par 1.0 de mouvement de prix et par lot (fx_usdb/jpy : divisé par prix)
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 50.0
    spread: float = 0.0       # spread moyen en unités de prix (hors annonces)
    slippage: float = 0.0     # slippage moyen par exécution au marché/stop (unités de prix)
    commission_lot: float = 0.0   # USD par lot, aller-retour
    swap_long: float = 0.0    # USD par lot et par nuit
    swap_short: float = 0.0
    tz: str = "UTC"           # fuseau de la place principale
    group: str = ""           # groupe de corrélation (plafond de risque)
    session_open: tuple = (8, 0)  # heure locale d'ouverture de la séance principale
    session_tz: str = ""
    tick: float = 0.0001



def _fx(n, spread, group, kind="fx_usdq", tick=0.00001, tz="Europe/London", so=(8, 0), swl=-4.0, sws=1.0):
    u = 100000.0
    return Spec(n, kind, u, spread=spread, slippage=spread * 0.3, commission_lot=7.0, swap_long=swl,
                swap_short=sws, group=group, tick=tick, tz=tz, session_open=so, session_tz=tz)


SPECS: dict[str, Spec] = {s.name: s for s in [
    Spec("US500", "index", 1.0, spread=0.5, slippage=0.3, tz="America/New_York", group="US_IDX",
         session_open=(9, 30), session_tz="America/New_York", tick=0.1, swap_long=-3.0, swap_short=-1.0),
    Spec("US100", "index", 1.0, spread=1.5, slippage=0.8, tz="America/New_York", group="US_IDX",
         session_open=(9, 30), session_tz="America/New_York", tick=0.1, swap_long=-3.0, swap_short=-1.0),
    Spec("US30", "index", 1.0, spread=2.0, slippage=1.0, tz="America/New_York", group="US_IDX",
         session_open=(9, 30), session_tz="America/New_York", tick=0.1, swap_long=-3.0, swap_short=-1.0),
    Spec("GER40", "index", 1.1, spread=1.0, slippage=0.5, tz="Europe/Berlin", group="EU_IDX",
         session_open=(9, 0), session_tz="Europe/Berlin", tick=0.1, swap_long=-3.0, swap_short=-1.0),
    Spec("XAUUSD", "metal", 100.0, spread=0.25, slippage=0.1, commission_lot=0.0, tz="Europe/London",
         group="METALS", session_open=(8, 0), session_tz="Europe/London", tick=0.01, swap_long=-15.0, swap_short=5.0),
    _fx("EURUSD", 0.00008, "USD_FX"), _fx("GBPUSD", 0.00010, "USD_FX"), _fx("AUDUSD", 0.00010, "USD_FX"),
    replace(_fx("AUDCAD", 0.00014, "CAD_FX", kind="fx_cross", tz="Australia/Sydney", so=(8, 0), swl=-2.0, sws=-1.0),
            usd_per_unit=100000.0 / USDCAD_REF),           # AUDCAD : cotée en CAD, 1 lot = 100 000 AUD
    Spec("USDJPY", "fx_jpy", 100000.0 / USDJPY_REF, spread=0.008, slippage=0.003, commission_lot=7.0,
         tz="Asia/Tokyo", group="JPY_FX", session_open=(9, 0), session_tz="Asia/Tokyo", tick=0.001,
         swap_long=3.0, swap_short=-6.0),
    Spec("GBPJPY", "fx_jpy", 100000.0 / USDJPY_REF, spread=0.020, slippage=0.006, commission_lot=7.0,
         tz="Europe/London", group="JPY_FX", session_open=(8, 0), session_tz="Europe/London", tick=0.001,
         swap_long=3.0, swap_short=-6.0),
    Spec("BTCUSD", "crypto", 1.0, min_lot=0.01, lot_step=0.01, spread=15.0, slippage=8.0, tz="UTC",
         group="CRYPTO", session_open=(0, 0), session_tz="UTC", tick=0.01, swap_long=-20.0, swap_short=-20.0),
]}


def value_per_unit(spec: Spec, price: float) -> float:
    """USD par unité de prix et par lot (conversion de devise approximative [HYPOTHÈSE])."""
    if spec.kind == "fx_jpy":
        return spec.usd_per_unit  # = 100000/USDJPY_REF  (taux de conversion figé)
    if spec.kind == "fx_usdb":
        return spec.usd_per_unit / price
    return spec.usd_per_unit


def get_spec(name: str) -> Spec:
    return SPECS[name]
