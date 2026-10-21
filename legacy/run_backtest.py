import argparse

from micro_scalping.backtester import Backtester
from micro_scalping.config import ScalpingConfig
from micro_scalping.data_loader import fetch_ohlcv_ccxt, generate_synthetic_ohlcv
from micro_scalping.stats import summarize


def main():
    parser = argparse.ArgumentParser(description="Micro-scalping strategy backtest")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--bars", type=int, default=3000)
    parser.add_argument("--trades", type=int, default=100, help="Stop once this many trades close")
    parser.add_argument(
        "--live-data", action="store_true", help="Fetch real OHLCV from Binance via ccxt"
    )
    args = parser.parse_args()

    if args.live_data:
        df = fetch_ohlcv_ccxt(args.symbol, args.timeframe, args.bars)
    else:
        df = generate_synthetic_ohlcv(args.bars)

    cfg = ScalpingConfig()
    bt = Backtester(cfg, target_trades=args.trades)
    trades = bt.run(df)

    stats = summarize(trades, cfg.initial_equity)
    source = "live" if args.live_data else "synthetic"
    print(f"\n=== Micro-Scalping Backtest ({source} data, {args.symbol} {args.timeframe}) ===")
    for k, v in stats.items():
        print(f"{k:18s}: {v}")

    print(f"\nLast {min(10, len(trades))} trades:")
    for t in trades[-10:]:
        print(
            f"{t.entry_time} {t.side:5s} entry={t.entry_price:.2f} exit={t.exit_price:.2f} "
            f"reason={t.reason:6s} pnl={t.pnl:+.2f}"
        )


if __name__ == "__main__":
    main()
