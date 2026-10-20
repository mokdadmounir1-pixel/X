"""Démonstration de bout en bout sur données SYNTHÉTIQUES (aucune donnée de
marché ici) : relecture -> livre virtuel -> FTMO -> MC de sensibilité.
Écrit outputs/prospective_demo.json. Ne prouve aucun avantage."""
import json
import os
import shutil
import tempfile

import numpy as np
import pandas as pd

from fx_liquidity_bot.config import StrategyConfig
from fx_liquidity_bot.data.loader import generate_synthetic_universe
from prop_sim import ftmo_mc
from prop_sim.book import VirtualBook
from prop_sim.ftmo import FtmoRules, evaluate
from prop_sim.replay import STRATEGY_ID, run, strategy_params

BARS, BAR_MIN, SEED = 20_000, 15, 7


def make_book(path, cfg):
    b = VirtualBook(path)
    b.register_strategy(STRATEGY_ID, strategy_params(cfg))
    b.set_strategy_status(STRATEGY_ID, "forward_test")
    return b


def summarize(b):
    t = b.trades()
    return {"trades": len(t), "balance": round(b.balance, 2), "equity": round(b.equity(), 2),
            "rejections": b.rejection_summary()}


def main():
    cfg = StrategyConfig()
    cfg.apply_preset("selective")
    data = generate_synthetic_universe(cfg.pairs, n_bars=BARS, seed=SEED, bar_minutes=BAR_MIN)
    d = tempfile.mkdtemp()
    try:
        full = make_book(os.path.join(d, "full.db"), cfg)
        run(full, data, cfg)
        s_full = summarize(full)

        # Reprise : arrêt au milieu, réouverture, rejeu COMPLET du flux.
        mid = data[cfg.pairs[0]].index[BARS // 2]
        part = make_book(os.path.join(d, "part.db"), cfg)
        run(part, data, cfg, stop_after=mid)
        part.close()
        part = make_book(os.path.join(d, "part.db"), cfg)
        run(part, data, cfg)
        s_part = summarize(part)
        resume_identical = (s_full["trades"], s_full["balance"]) == (s_part["trades"], s_part["balance"])

        eq = full.equity_curve()
        rules = FtmoRules()
        res = evaluate(eq, full.trading_days(), rules)
        t = full.trades()
        r_mult = (t.pnl / (t.risk_pct / 100 * 100_000)).to_numpy() if len(t) else np.array([])
        years = (eq.index[-1] - eq.index[0]).days / 365.25
        dd = float(((eq.equity.cummax() - eq.equity) / eq.equity.cummax()).max() * 100)
    finally:
        pass

    out = {
        "source": "SYNTHETIC random-walk fixture (fx_liquidity_bot.data.loader) - not market data",
        "window": [str(eq.index[0]), str(eq.index[-1])], "bars_per_pair": BARS, "bar_minutes": BAR_MIN,
        "spread_source": "typical spreads from config (research placeholder, not measured bid/ask)",
        "run": s_full,
        "net_return_pct": round((s_full["balance"] / rules.initial_balance - 1) * 100, 2),
        "max_equity_drawdown_pct": round(dd, 2),
        "total_costs_usd": round(float(t.costs.sum()), 2) if len(t) else 0.0,
        "years_covered": round(years, 2),
        "resume_check": {"identical_after_restart_and_full_replay": bool(resume_identical),
                         "full": s_full["trades"], "resumed": s_part["trades"]},
        "ftmo_replay_result": {k: str(v) for k, v in vars(res).items()},
        "ftmo_rules_verified_on": rules.verified_on,
    }

    # Sensibilité conditionnelle (hypothèses d'espérance, PAS le résultat de NEXUS)
    grid = []
    for p_win, win_r in [(0.40, 1.5), (0.45, 1.5), (0.50, 1.5), (0.40, 2.0)]:
        for risk in (0.25, 0.60, 1.0):
            e = ftmo_mc.expectancy(p_win, win_r, 0.05)
            r = ftmo_mc.simulate(ftmo_mc.bernoulli_sampler(p_win, win_r), risk, trades_per_day=2,
                                 n_sims=2000, seed=1)
            grid.append({"p_win": p_win, "win_R": win_r, "expectancy_R_net": round(e, 3),
                         "risk_pct": risk, "pass": round(r["passed"]["p"], 3),
                         "pass_ci95": [round(x, 3) for x in r["passed"]["ci95"]],
                         "fail_daily": round(r["failed_daily_loss"]["p"], 3),
                         "fail_max": round(r["failed_max_loss"]["p"], 3),
                         "incomplete_60d": round(r["incomplete"]["p"], 3),
                         "median_days_to_pass": r["median_days_to_pass"],
                         "p_day_ge_3pct": round(r["p_any_day_gain_ge_3pct"], 4)})
    out["ftmo_sensitivity_conditional"] = grid
    if len(r_mult) >= 30:
        r = ftmo_mc.simulate(ftmo_mc.bootstrap_sampler(r_mult), 0.25, 2, n_sims=2000, seed=2)
        out["ftmo_bootstrap_from_synthetic_trades"] = {
            "n_trades_resampled": int(len(r_mult)), "mean_R": round(float(r_mult.mean()), 3),
            "pass": round(r["passed"]["p"], 3), "fail_daily": round(r["failed_daily_loss"]["p"], 3),
            "fail_max": round(r["failed_max_loss"]["p"], 3),
            "note": "échantillon synthétique : illustre la mécanique, n'estime aucun résultat réel"}
    os.makedirs("outputs", exist_ok=True)
    with open("outputs/prospective_demo.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(json.dumps({k: v for k, v in out.items() if k != "ftmo_sensitivity_conditional"}, indent=2, default=str))
    shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    main()
