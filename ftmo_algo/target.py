"""Module « cible mensuelle » : MESURE (jamais objectif d'optimisation) de la probabilité d'atteindre +5 %/mois.
Rééchantillonne À LA FOIS le nombre de trades par mois (distribution observée) et leurs résultats (blocs
chronologiques consécutifs : les regroupements de pertes sont conservés). Les trades en entrée sont figés ;
seul le risque par trade est cherché, sous contrainte P(violation) < 5 %."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .engine.guardian import PropProfile

RISKS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5]


def _prep(trades: pd.DataFrame):
    t = trades.sort_values("exit_t").reset_index(drop=True)
    ts = pd.to_datetime(t.exit_t, utc=True)
    day = ((ts.dt.tz_convert("Europe/Prague").dt.tz_localize(None).dt.normalize().astype("int64") // 86_400_000_000_000)
           .to_numpy())
    month = ts.dt.tz_localize(None).dt.to_period("M")
    full = pd.period_range(month.min(), month.max(), freq="M")
    counts = month.value_counts().reindex(full, fill_value=0).to_numpy()
    return t.r.to_numpy("float64"), day, counts


def _month(r, day, counts, rng, risk, prof: PropProfile, eq0, daily_guard, total_guard_floor):
    """Simule un mois : retourne (rendement fractionnaire, violation, bloqué, jours de trading)."""
    n = int(rng.choice(counts))
    if n == 0 or len(r) == 0:
        return 0.0, False, False, 0, 0.0
    s = int(rng.integers(0, len(r)))
    idx = (s + np.arange(n)) % len(r)
    rr, dd = r[idx], day[idx]
    eq = eq0; cur_day = None; day_start = eq0; viol = False; blocked = False; days = set(); worst = eq0
    for x, d in zip(rr, dd):
        if d != cur_day:
            cur_day, day_start = d, eq
        if blocked and d == cur_day and eq - day_start <= -daily_guard:
            continue
        if eq <= total_guard_floor:
            blocked = True
            break
        if prof.daily_loss_pct > 0 and eq - day_start <= -daily_guard:
            continue
        eq += x * risk / 100.0
        days.add(d)
        worst = min(worst, eq)
        if prof.daily_loss_pct > 0 and day_start - eq >= prof.daily_loss_pct / 100:
            viol = True
        if eq <= 1.0 - prof.max_loss_pct / 100:
            viol = True
    return eq - eq0, viol, blocked, len(days), worst


def monthly_mc(trades: pd.DataFrame, risk_pct: float, prof: PropProfile, paths=3000, horizon_months=3, seed=0,
               target_pct=5.0):
    if len(trades) < 10:
        return {"status": "échantillon insuffisant (< 10 trades)"}
    r, day, counts = _prep(trades)
    rng = np.random.default_rng(seed)
    g = prof.guardian
    dg = prof.daily_loss_pct / 100 * g["daily_frac"] if prof.daily_loss_pct > 0 else 1e9
    floor = 1.0 - prof.max_loss_pct / 100 * g["total_frac"]
    m1, viol, passed1, passedH, blockedH = [], 0, 0, 0, 0
    for _ in range(paths):
        eq, v, done1, doneH, ndays = 1.0, False, False, False, 0
        for m in range(horizon_months):
            ret, vm, bl, nd, _w = _month(r, day, counts, rng, risk_pct, prof, eq, dg, floor)
            if m == 0:
                m1.append(ret)
            eq += ret; ndays += nd; v = v or vm
            if v:
                break
            if bl:
                blockedH += 1; break
            if eq - 1.0 >= prof.profit_target_pct / 100 and ndays >= prof.min_trading_days:
                if m == 0:
                    done1 = True
                doneH = True; break
        viol += v; passed1 += (done1 and not v); passedH += (doneH and not v)
    m1 = np.array(m1) * 100
    return {"status": "ok", "risk_pct": risk_pct, "p_month_ge_target": round(float((m1 >= target_pct).mean()), 4),
            "median_month_pct": round(float(np.median(m1)), 3), "p_month_negative": round(float((m1 < 0).mean()), 4),
            "p_violation": round(viol / paths, 4), "p_challenge_1m": round(passed1 / paths, 4),
            f"p_challenge_{horizon_months}m": round(passedH / paths, 4), "p_blocked_by_guardian": round(blockedH / paths, 4),
            "mean_trades_per_month": round(float(counts.mean()), 2), "months_observed": int(len(counts)),
            "month_p5_p95": [round(float(np.percentile(m1, 5)), 2), round(float(np.percentile(m1, 95)), 2)]}


def recommend(trades: pd.DataFrame, prof: PropProfile, target_pct=5.0, max_violation=0.05, paths=2000, seed=0):
    """Risque maximisant P(mois ≥ cible) sous P(violation) < 5 %. Les trades ne sont jamais modifiés."""
    rows = [monthly_mc(trades, rk, prof, paths=paths, seed=seed, target_pct=target_pct) for rk in RISKS]
    if rows[0].get("status") != "ok":
        return {"status": rows[0].get("status"), "grid": []}
    safe = [x for x in rows if x["p_violation"] < max_violation]
    if not safe:
        return {"status": "aucun risque de la grille ne respecte P(violation)<5 %", "grid": rows, "recommended": None}
    best = max(safe, key=lambda x: (x["p_month_ge_target"], -x["risk_pct"]))
    reachable = best["p_month_ge_target"] > 0.5
    return {"status": "ok", "grid": rows, "recommended": best,
            "max_safe_risk": max(x["risk_pct"] for x in safe),
            "verdict": ("cible atteignable (P>50 %)" if reachable else
                        f"cible NON atteignable de façon fiable ; rendement mensuel réaliste médian {best['median_month_pct']} %")}
