"""Research protocol. A strategy only earns PASS if it survives out-of-sample,
beats a no-structure null market, survives 2x costs and isn't carried by 3 trades."""
from __future__ import annotations

import itertools
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .engine import EngineCfg, run
from .metrics import monte_carlo, summarize
from .strategies import REGISTRY
from .synth import block_bootstrap

RESULTS = Path(__file__).resolve().parents[1] / "results"


def evaluate(name, params, df, cfg):
    s = REGISTRY[name](**params).signals(df)
    tr, eq = run(df, s, cfg)
    return summarize(tr, eq, cfg.equity), tr, eq


def _score(m, min_trades=15):
    # robust objective: expectancy in R, shrunk by sample size, penalised by drawdown
    if m["trades"] < min_trades:
        return -9.0
    return m["expectancy_r"] * np.sqrt(m["trades"]) / (1 + abs(m["max_dd_pct"]) / 20)


def optimise(name, df, cfg, n_iter=40, seed=0):
    grid = REGISTRY[name].grid
    combos = [dict(zip(grid, v)) for v in itertools.product(*grid.values())]
    rng = np.random.default_rng(seed)
    if len(combos) > n_iter:
        combos = [combos[i] for i in rng.choice(len(combos), n_iter, replace=False)]
    best, best_s = {}, -1e9
    for p in combos or [{}]:
        m, _, _ = evaluate(name, p, df, cfg)
        sc = _score(m)
        if sc > best_s:
            best, best_s = p, sc
    return best, best_s


def walk_forward(name, df, cfg, splits=4, train_frac=0.6, n_iter=30):
    """Anchored-size rolling windows: optimise on train, trade the next unseen block."""
    n = len(df)
    block = n // (splits + 1)
    tr_len = int(block * train_frac / (1 - train_frac)) if splits else n
    oos_trades, params_used = [], []
    eq_chain = []
    for k in range(splits):
        te_s = tr_len + k * block if tr_len + (k + 1) * block <= n else n - block
        tr_df, te_df = df.iloc[max(0, te_s - tr_len):te_s], df.iloc[te_s:te_s + block]
        p, _ = optimise(name, tr_df, cfg, n_iter)
        m, t, eq = evaluate(name, p, te_df, cfg)
        oos_trades.append(t)
        params_used.append(p)
        eq_chain.append(eq - cfg.equity)
    allt = pd.concat([t for t in oos_trades if len(t)], ignore_index=True) if any(len(t) for t in oos_trades) else pd.DataFrame(columns=["pnl", "r", "fees"])
    pnl_curve = pd.concat(eq_chain).pipe(lambda s: s[~s.index.duplicated()]) if eq_chain else pd.Series(dtype=float)
    return allt, params_used, pnl_curve


def null_test(name, params, df, cfg, n=30, block=60):
    real, _, _ = evaluate(name, params, df, cfg)
    sc = []
    for k in range(n):
        m, _, _ = evaluate(name, params, block_bootstrap(df, block, seed=k), cfg)
        sc.append(m["expectancy_r"] if m["trades"] >= 10 else -1.0)
    sc = np.array(sc)
    p = float((np.sum(sc >= real["expectancy_r"]) + 1) / (n + 1))
    return dict(real_exp_r=real["expectancy_r"], null_mean=float(sc.mean()), null_p95=float(np.percentile(sc, 95)), p_value=p)


def cost_curve(name, params, df, cfg, ks=(0, 0.5, 1, 2, 3)):
    out = {}
    for k in ks:
        m, _, _ = evaluate(name, params, df, cfg.scaled_costs(k))
        out[str(k)] = dict(expectancy_r=m["expectancy_r"], net=m["net"], trades=m["trades"])
    return out


def full_report(name, df, cfg=None, splits=4, n_iter=30, null_n=20):
    cfg = cfg or EngineCfg()
    t0 = time.time()
    oos, params_used, pnl_curve = walk_forward(name, df, cfg, splits, n_iter=n_iter)
    # params for the null/cost tests: the most recently selected set (what we would actually trade)
    p_live = params_used[-1] if params_used else {}
    n = len(oos)
    exp_r = float(oos.r.mean()) if n else 0.0
    net = float(oos.pnl.sum()) if n else 0.0
    pf = float(min(99.0, oos.pnl[oos.pnl > 0].sum() / max(-oos.pnl[oos.pnl < 0].sum(), 1e-9))) if n else 0.0
    mc = monte_carlo(oos.pnl.values if n else np.array([]), cfg.equity)
    top3 = float(oos.pnl.nlargest(3).sum() / net) if n and net > 0 else 1.0
    nl = null_test(name, p_live, df, cfg, null_n)
    costs = cost_curve(name, p_live, df, cfg)
    gates = {
        "enough_trades(>=60)": n >= 60,
        "oos_expectancy>0": exp_r > 0,
        "oos_profit_factor>1.15": pf > 1.15,
        "beats_null(p<0.10)": nl["p_value"] < 0.10,
        "survives_2x_costs": costs["2"]["expectancy_r"] > 0,
        "mc_p5_equity>start": mc["p5_final"] > cfg.equity,
        "not_top3_driven(<50%)": top3 < 0.5,
    }
    passed = sum(gates.values())
    verdict = "PASS" if passed == len(gates) else ("WATCH" if passed >= 5 and gates["oos_expectancy>0"] else "FAIL")
    return dict(strategy=name, desc=REGISTRY[name].desc, verdict=verdict, gates_passed=passed, gates=gates,
                oos=dict(trades=n, expectancy_r=exp_r, net=net, profit_factor=pf, win_rate=float((oos.pnl > 0).mean() * 100) if n else 0.0,
                         avg_fee_r=float((oos.fees / (oos.pnl / oos.r).abs()).mean()) if n else 0.0),
                monte_carlo=mc, null=nl, costs=costs, params=p_live, seconds=round(time.time() - t0, 1),
                oos_curve=[float(x) for x in pnl_curve.iloc[::max(1, len(pnl_curve) // 120)]] if len(pnl_curve) else [])


def run_all(df, names=None, source="synthetic", **kw):
    names = names or [n for n in REGISTRY if n != "ml_direction"]
    reps = [full_report(n, df, **kw) for n in names]
    reps.sort(key=lambda r: (r["gates_passed"], r["oos"]["expectancy_r"]), reverse=True)
    out = dict(ts=int(time.time()), source=source, bars=len(df), reports=reps)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "latest.json").write_text(json.dumps(out, indent=1))
    return out
