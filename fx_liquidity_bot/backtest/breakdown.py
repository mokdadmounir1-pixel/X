import pandas as pd


def trades_to_df(trades: list) -> pd.DataFrame:
    rows = []
    for t in trades:
        rows.append({
            "pair": t.pair, "direction": t.direction, "entry_time": t.entry_time,
            "exit_time": t.exit_time, "pnl_usd": t.pnl_usd, "reason": t.reason,
            "score": t.score, "rr": t.rr, "regime": t.regime, "session": t.session,
            "tp_source": t.tp_source, "hour": t.entry_time.hour,
            "day_of_week": t.entry_time.day_name(),
        })
    return pd.DataFrame(rows)


def breakdown_by(trades: list, key: str) -> pd.DataFrame:
    df = trades_to_df(trades)
    if df.empty:
        return df
    g = df.groupby(key)["pnl_usd"]
    out = g.agg(trades="count", win_rate=lambda s: round(100 * (s > 0).mean(), 1),
                net_pnl="sum", avg_pnl="mean")
    return out.sort_values("net_pnl", ascending=False)


def full_breakdown(trades: list) -> dict:
    return {
        "by_pair": breakdown_by(trades, "pair"),
        "by_hour": breakdown_by(trades, "hour"),
        "by_session": breakdown_by(trades, "session"),
        "by_day_of_week": breakdown_by(trades, "day_of_week"),
        "by_regime": breakdown_by(trades, "regime"),
        "by_direction": breakdown_by(trades, "direction"),
    }
