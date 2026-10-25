"""Spécifications de contrat des symboles (swaps, taille de contrat, pas de prix, marge...) en LECTURE SEULE.

    python scripts/export_symbol_specs.py --symbols XAUUSD EURUSD USTEC --out data/deep/SYMBOL-SPECS.json

Aucun appel d'ordre. Sert à remplacer les hypothèses de swap/coûts par les valeurs réelles du compte.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ["name", "description", "currency_base", "currency_profit", "currency_margin", "digits", "point", "trade_contract_size",
          "trade_tick_size", "trade_tick_value", "trade_tick_value_profit", "trade_tick_value_loss", "volume_min", "volume_step", "volume_max",
          "swap_mode", "swap_long", "swap_short", "swap_rollover3days", "trade_calc_mode", "trade_mode", "trade_exemode", "filling_mode",
          "trade_stops_level", "trade_freeze_level", "margin_initial", "margin_maintenance", "spread", "spread_float"]


def main(argv=None, mt5=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="+", default=["XAUUSD"]); ap.add_argument("--out", default="data/deep/SYMBOL-SPECS.json")
    ap.add_argument("--terminal", default=None, help="chemin de terminal64.exe (indispensable si deux terminaux MT5 sont installés)")
    args = ap.parse_args(argv)
    if mt5 is None:
        import MetaTrader5 as mt5  # type: ignore
    if not (mt5.initialize(args.terminal) if args.terminal else mt5.initialize()):
        raise SystemExit(f"initialize() a échoué : {mt5.last_error()}")
    try:
        out = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "orders_sent": 0, "symbols": {}}
        for s in args.symbols:
            info = mt5.symbol_info(s)
            out["symbols"][s] = None if info is None else {f: getattr(info, f, None) for f in FIELDS}
        p = Path(args.out); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"écrit : {p}")
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
