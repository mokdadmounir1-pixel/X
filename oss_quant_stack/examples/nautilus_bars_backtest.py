"""NautilusTrader : backtest événementiel sur des barres M15 (démonstration de plomberie, PAS une validation).

    python examples/nautilus_bars_backtest.py chemin/vers/EURUSD_M15.csv

Instrument de test EUR/USD fourni par Nautilus ; le CSV est un export MT5 de quantbot. Stratégie : croisement EMA 20/50 FIGÉ, long/short, taille fixe. Les 12 derniers mois ne sont pas lus.
Nautilus n'a pas d'adaptateur MetaTrader 5 : il sert ici à la recherche/backtest, pas à l'exécution sur ton MT5.
"""
import argparse, sys
from decimal import Decimal

import pandas as pd
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money, Quantity
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.trading.strategy import Strategy


class EmaCross(Strategy):
    def __init__(self, config) -> None:
        super().__init__(config); self.fast = ExponentialMovingAverage(20); self.slow = ExponentialMovingAverage(50); self.prev = 0

    def on_start(self) -> None:
        self.register_indicator_for_bars(self.config.bar_type, self.fast); self.register_indicator_for_bars(self.config.bar_type, self.slow)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if not self.indicators_initialized():
            return
        sign = 1 if self.fast.value > self.slow.value else -1
        if sign != self.prev:
            self.close_all_positions(self.config.instrument_id)
            side = OrderSide.BUY if sign > 0 else OrderSide.SELL
            self.submit_order(self.order_factory.market(self.config.instrument_id, side, Quantity.from_int(100_000)))
            self.prev = sign


class EmaCrossConfig(StrategyConfig, frozen=True):
    instrument_id: object
    bar_type: object


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("csv"); a = ap.parse_args(argv)
    raw = pd.read_csv(a.csv); raw["time"] = pd.to_datetime(raw["time"], utc=True); raw = raw.set_index("time").sort_index()
    raw = raw[raw.index <= raw.index[-1] - pd.DateOffset(months=12)][["open", "high", "low", "close", "volume"]]
    if len(raw) < 500:
        print("Historique trop court après retrait des 12 derniers mois (moins de 500 barres) : rien à faire.", file=sys.stderr); return 2
    inst = TestInstrumentProvider.default_fx_ccy("EUR/USD"); bar_type = BarType.from_str(f"{inst.id}-15-MINUTE-MID-EXTERNAL")
    bars = BarDataWrangler(bar_type, inst).process(raw)
    engine = BacktestEngine(config=BacktestEngineConfig())
    engine.add_venue(venue=Venue("SIM"), oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=USD, starting_balances=[Money(100_000, USD)])
    engine.add_instrument(inst); engine.add_data(bars)
    engine.add_strategy(EmaCross(EmaCrossConfig(instrument_id=inst.id, bar_type=bar_type)))
    engine.run()
    rep = engine.trader.generate_positions_report(); print(f"Positions clôturées : {len(rep)}")
    print(engine.portfolio.analyzer.get_performance_stats_pnls())
    print("Démonstration de plomberie uniquement : aucune conclusion de trading.")
    engine.dispose(); return 0


if __name__ == "__main__":
    sys.exit(main())
