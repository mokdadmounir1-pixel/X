"""Audit de performance sur les journaux RÉELS (trades simulés PAPER, journal d'exécution, ticks). Aucune valeur par défaut inventée : ce qui n'est pas mesuré est « non mesuré »."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .lab.stats import sign_flip_pvalue


def trade_metrics(rs) -> dict:
    """Espérance, facteur de profit, taux de réussite avec son seuil d'équilibre, R:R réalisé, drawdown cumulé (en R), p-valeur du test nul, Sharpe/Sortino par trade."""
    r = np.asarray([x for x in rs if x is not None and np.isfinite(x)], float); n = len(r)
    if n == 0:
        return {"n": 0}
    w, l = r[r > 0], r[r <= 0]; gross_w, gross_l = float(w.sum()), float(-l.sum())
    avg_w = float(w.mean()) if len(w) else 0.0; avg_l = float(-l.mean()) if len(l) else 0.0
    rr = avg_w / avg_l if avg_l > 0 and avg_w > 0 else None
    cum = np.cumsum(r); dd = float((np.maximum.accumulate(np.r_[0.0, cum])[1:] - cum).max())
    down = float(np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)))
    return {"n": n, "win_rate": float(len(w) / n), "avg_win_r": avg_w, "avg_loss_r": avg_l, "realised_rr": rr, "breakeven_wr": (1.0 / (1.0 + rr)) if rr else None,
            "expectancy_r": float(r.mean()), "profit_factor": (gross_w / gross_l) if gross_l > 0 else (math.inf if gross_w > 0 else 0.0),
            "sharpe_per_trade": float(r.mean() / r.std(ddof=1)) if n > 2 and r.std(ddof=1) > 0 else None, "sortino_per_trade": float(r.mean() / down) if down > 0 else None,
            "max_drawdown_r": dd, "sign_flip_p": sign_flip_pvalue(r) if n >= 5 else None}


def gatekeeper(m: dict, min_trades: int = 60, min_pf: float = 1.40, alpha: float = 0.05, max_dd_frac: float | None = None, dd_frac: float | None = None,
               latency_ms: dict | None = None, max_latency_ms: float = 25.0) -> list[dict]:
    """Conditions de passage, chacune avec son état OK / ÉCHEC / NON MESURÉ. Aucune ne vaut approbation ; le passage au réel reste une décision humaine écrite."""
    def chk(name, ok, detail):
        return {"check": name, "state": "NON MESURE" if ok is None else ("OK" if ok else "ECHEC"), "detail": detail}
    n = m.get("n", 0); out = [chk("échantillon >= %d trades" % min_trades, n >= min_trades, f"{n} trades")]
    if n:
        out += [chk("espérance nette > 0", m["expectancy_r"] > 0, f"{m['expectancy_r']:+.3f} R"),
                chk("facteur de profit >= %.2f" % min_pf, m["profit_factor"] >= min_pf, f"{m['profit_factor']:.2f}"),
                chk("taux de réussite > seuil d'équilibre", None if m["breakeven_wr"] is None else m["win_rate"] > m["breakeven_wr"],
                    f"{m['win_rate']:.1%} vs {m['breakeven_wr']:.1%}" if m["breakeven_wr"] else "R:R non défini"),
                chk("test nul (sign-flip) p <= %.2f" % alpha, None if m["sign_flip_p"] is None else m["sign_flip_p"] <= alpha, f"p = {m['sign_flip_p']}")]
    out.append(chk("drawdown <= %.2f%%" % ((max_dd_frac or 0.008) * 100), None if dd_frac is None else dd_frac <= (max_dd_frac or 0.008), "non mesuré" if dd_frac is None else f"{dd_frac:.2%}"))
    out.append(chk("latence max <= %g ms" % max_latency_ms, None if not latency_ms else latency_ms["max"] <= max_latency_ms, "aucun ordre envoyé : non mesuré" if not latency_ms else f"max {latency_ms['max']:.1f} ms"))
    return out


def execution_stats(rows: list[dict]) -> dict:
    """Latence (ms) et glissement (prix, positif = défavorable) depuis le journal d'exécution append-only."""
    lat = np.array([r["latency_ms"] for r in rows if r.get("latency_ms") is not None], float); sl = np.array([r["slippage"] for r in rows if r.get("slippage") is not None], float)
    if not len(lat) and not len(sl):
        return {}
    q = lambda a, p: float(np.percentile(a, p)) if len(a) else None
    return {"n": int(len(rows)), "latency_ms": {"median": q(lat, 50), "p95": q(lat, 95), "p99": q(lat, 99), "max": float(lat.max()) if len(lat) else None},
            "slippage": {"mean": float(sl.mean()) if len(sl) else None, "p95": q(sl, 95)}}


def tick_inventory(root: Path) -> dict:
    """État des ticks réels enregistrés : fichiers, lignes, étendue, plus grand trou, spread (quantiles, part <= 0,03 $)."""
    d = Path(root) / "data" / "live" / "ticks"; files = sorted(d.glob("*_2*.csv")) if d.exists() else []
    if not files:
        return {"files": 0, "note": "aucun tick enregistré : terminal non lancé, MT5 injoignable ou marché fermé"}
    df = pd.concat([pd.read_csv(f, usecols=["time_msc", "bid", "ask"]) for f in files]).drop_duplicates("time_msc").sort_values("time_msc")
    t = pd.to_datetime(df["time_msc"], unit="ms", utc=True); sp = (df["ask"] - df["bid"]).to_numpy(); gaps = t.diff().dt.total_seconds()
    return {"files": len(files), "ticks": int(len(df)), "start": str(t.iloc[0]), "end": str(t.iloc[-1]), "max_gap_s": float(gaps.max()) if len(gaps) > 1 else 0.0,
            "spread_p10_p50_p90": [float(np.percentile(sp, p)) for p in (10, 50, 90)], "share_spread_le_0_03": float((sp <= 0.03).mean())}
