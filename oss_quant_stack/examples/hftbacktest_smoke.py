"""hftbacktest : contrôle d'installation et de configuration d'un actif (aucun backtest : il exige des données de CARNET réelles).

    python examples/hftbacktest_smoke.py

hftbacktest rejoue ticks + profondeur (L2/L3) avec file d'attente et latences. Sans flux de profondeur réel, un backtest serait inventé : ce script ne lance donc rien de plus.
Les ticks bid/ask de quantbot (data/live/ticks/) n'ont pas de tailles : ils ne suffisent pas. Voir docs/HFTBACKTEST_DONNEES.md.
"""
import sys

import hftbacktest
from hftbacktest import BacktestAsset


def main() -> int:
    asset = (BacktestAsset().linear_asset(1.0).constant_latency(1_000_000, 1_000_000).risk_adverse_queue_model().no_partial_fill_exchange().tick_size(0.01).lot_size(0.01))
    print(f"hftbacktest {getattr(hftbacktest, '__version__', '?')} : actif XAUUSD configuré (tick 0,01, lot 0,01, latence 1 ms, file d'attente risk-averse) -> {type(asset).__name__}")
    print("Aucun backtest lancé : données de carnet réelles requises.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
