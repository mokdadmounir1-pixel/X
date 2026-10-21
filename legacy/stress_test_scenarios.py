"""Multi-scenario robustness stress test.

Generates N independent synthetic multi-year market histories (different
random seeds -- N different "charts") and runs the FX liquidity-sweep bot
on each one under two configs:

  - "permissive": looser score threshold / RR / daily cap -> more trades
  - "selective":  tighter score threshold / RR / daily cap -> fewer, more
                  selective trades

The point is to compare consistency across scenarios, not to prove edge on
synthetic data (see fx_liquidity_bot/README.md -- these are noisy self-test
fixtures, not a market simulator). Trading LESS selectively should show up
here as a *tighter* spread of outcomes across scenarios (lower std dev of
win rate / profit factor), even if the average edge is still close to flat
on data with no real structure.

Usage: python stress_test_scenarios.py [--scenarios 10] [--years 2] [--bar-minutes 15]
"""
import argparse
import copy
import time

import pandas as pd

from fx_liquidity_bot.backtest.metrics import summarize
from fx_liquidity_bot.config import StrategyConfig
from fx_liquidity_bot.data.loader import generate_synthetic_universe
from fx_liquidity_bot.engine.scanner import PortfolioScanner

CONFIGS = {
    "permissive": dict(score_threshold=50, min_rr=1.5, max_trades_per_day=10),
    "selective": dict(score_threshold=70, min_rr=2.0, max_trades_per_day=5),
}


def make_config(overrides: dict) -> StrategyConfig:
    cfg = StrategyConfig()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def daily_basket_preview(data: dict) -> pd.DataFrame:
    """Equal-weight basket of % return from start across all pairs, resampled
    daily -- a compact stand-in for 'the chart' of this scenario."""
    normed = []
    for pair, df in data.items():
        s = df["close"].resample("1D").last().dropna()
        normed.append(s / s.iloc[0] * 100)
    basket = pd.concat(normed, axis=1).mean(axis=1)
    return basket.rename("basket_pct").reset_index().rename(columns={"index": "date"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=10)
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--bar-minutes", type=int, default=15)
    parser.add_argument("--results-csv", default="/tmp/fx_scenarios_results.csv")
    parser.add_argument("--preview-csv", default="/tmp/fx_scenarios_price_preview.csv")
    args = parser.parse_args()

    bars_per_year = int(365 * 24 * 60 / args.bar_minutes)
    n_bars = int(bars_per_year * args.years)

    cfg_template = StrategyConfig()
    pairs = cfg_template.pairs

    results = []
    previews = []
    t_start = time.time()

    for scenario_id in range(1, args.scenarios + 1):
        seed = 1000 + scenario_id * 17
        data = generate_synthetic_universe(pairs, n_bars=n_bars, seed=seed, bar_minutes=args.bar_minutes)

        preview = daily_basket_preview(data)
        preview.insert(0, "scenario", scenario_id)
        previews.append(preview)

        for cfg_name, overrides in CONFIGS.items():
            cfg = make_config(overrides)
            scanner = PortfolioScanner(cfg)
            trades = scanner.run(data)
            stats = summarize(trades, cfg.initial_equity)
            stats.update({"scenario": scenario_id, "config": cfg_name})
            results.append(stats)

            elapsed = time.time() - t_start
            print(f"[{elapsed:7.1f}s] scenario {scenario_id:2d}/{args.scenarios} "
                  f"({cfg_name:10s}): trades={stats.get('trades', 0):3d} "
                  f"win_rate={stats.get('win_rate_pct', 'NA')} "
                  f"pf={stats.get('profit_factor', 'NA')} "
                  f"dd={stats.get('max_drawdown_pct', 'NA')}", flush=True)

    results_df = pd.DataFrame(results)
    results_df.to_csv(args.results_csv, index=False)
    pd.concat(previews, ignore_index=True).to_csv(args.preview_csv, index=False)

    print(f"\nTotal elapsed: {time.time() - t_start:.1f}s")
    print(f"Results written to {args.results_csv}")
    print(f"Price previews written to {args.preview_csv}")

    print("\n=== Aggregate comparison across scenarios ===")
    for cfg_name in CONFIGS:
        sub = results_df[results_df["config"] == cfg_name]
        traded = sub[sub["trades"] > 0]
        print(f"\n-- {cfg_name} --")
        print(f"scenarios with >=1 trade : {len(traded)}/{len(sub)}")
        print(f"total trades             : {sub['trades'].sum()}")
        print(f"avg trades/scenario      : {sub['trades'].mean():.1f}")
        if not traded.empty:
            print(f"win_rate_pct   mean={traded['win_rate_pct'].mean():.1f}  "
                  f"std={traded['win_rate_pct'].std():.1f}")
            print(f"profit_factor  mean={traded['profit_factor'].replace([float('inf')], None).mean():.2f}  "
                  f"std={traded['profit_factor'].replace([float('inf')], None).std():.2f}")
            print(f"return_pct     mean={traded['return_pct'].mean():.2f}  "
                  f"std={traded['return_pct'].std():.2f}")
            print(f"max_drawdown_pct mean={traded['max_drawdown_pct'].mean():.2f}  "
                  f"std={traded['max_drawdown_pct'].std():.2f}")
            print(f"scenarios profitable (net_pnl>0): {(traded['net_pnl'] > 0).sum()}/{len(traded)}")


if __name__ == "__main__":
    main()
