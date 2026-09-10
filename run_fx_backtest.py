import argparse
import os

from fx_liquidity_bot.backtest.breakdown import full_breakdown, trades_to_df
from fx_liquidity_bot.backtest.metrics import summarize
from fx_liquidity_bot.backtest.montecarlo import monte_carlo
from fx_liquidity_bot.backtest.walkforward import walk_forward
from fx_liquidity_bot.config import StrategyConfig
from fx_liquidity_bot.data.loader import generate_synthetic_universe, load_csv
from fx_liquidity_bot.engine.scanner import PortfolioScanner
from fx_liquidity_bot.journal import build_journal


def main():
    parser = argparse.ArgumentParser(description="Liquidity sweep + displacement + FVG forex backtest")
    parser.add_argument("--bars", type=int, default=20_000, help="Bars per pair for synthetic data")
    parser.add_argument("--data-dir", default=None, help="Dir with one <PAIR>.csv per pair; omit for synthetic data")
    parser.add_argument("--journal-csv", default=None)
    parser.add_argument("--trades-csv", default=None)
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--monte-carlo", action="store_true")
    parser.add_argument("--preset", choices=["permissive", "selective"], default=None,
                         help="Apply a validated score/RR/daily-cap combo (see README); "
                              "individual --score-threshold/--min-rr/--max-trades-per-day override it")
    parser.add_argument("--score-threshold", type=float, default=None)
    parser.add_argument("--min-rr", type=float, default=None)
    parser.add_argument("--max-trades-per-day", type=int, default=None)
    args = parser.parse_args()

    cfg = StrategyConfig()
    if args.preset is not None:
        cfg.apply_preset(args.preset)
    if args.score_threshold is not None:
        cfg.score_threshold = args.score_threshold
    if args.min_rr is not None:
        cfg.min_rr = args.min_rr
    if args.max_trades_per_day is not None:
        cfg.max_trades_per_day = args.max_trades_per_day

    if args.data_dir:
        data = {p: load_csv(os.path.join(args.data_dir, f"{p}.csv")) for p in cfg.pairs}
    else:
        data = generate_synthetic_universe(cfg.pairs, n_bars=args.bars)

    scanner = PortfolioScanner(cfg)
    trades = scanner.run(data)

    print(f"\n=== Liquidity Sweep + Displacement + FVG bot -- {len(trades)} trades, {len(cfg.pairs)} pairs ===")
    stats = summarize(trades, cfg.initial_equity)
    for k, v in stats.items():
        print(f"{k:22s}: {v}")

    print("\n--- Breakdown ---")
    for name, df in full_breakdown(trades).items():
        print(f"\n{name}:")
        print(df if not df.empty else "  (no trades)")

    journal_df = build_journal(scanner)
    print(f"\nJournal entries: {len(journal_df)}")
    if not journal_df.empty:
        print(journal_df["status"].value_counts().to_string())
    if args.journal_csv and not journal_df.empty:
        journal_df.to_csv(args.journal_csv, index=False)
        print(f"Journal written to {args.journal_csv}")

    if args.trades_csv and trades:
        trades_to_df(trades).to_csv(args.trades_csv, index=False)
        print(f"Trades written to {args.trades_csv}")

    per_day = {}
    for t in trades:
        d = t.entry_time.date()
        per_day[d] = per_day.get(d, 0) + 1
    if per_day:
        print(f"\nMax trades in a single day: {max(per_day.values())} (cap={cfg.max_trades_per_day})")

    if args.walk_forward:
        print("\n--- Walk-forward (fixed params, chronological folds) ---")
        print(walk_forward(data, cfg, n_folds=4))

    if args.monte_carlo:
        print("\n--- Monte Carlo (trade resampling) ---")
        print(monte_carlo(trades, cfg.initial_equity))


if __name__ == "__main__":
    main()
