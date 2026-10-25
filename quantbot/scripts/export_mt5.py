"""Export de l'historique MetaTrader 5 au format attendu par quantbot (à lancer sur la machine Windows où tourne MT5).

    pip install MetaTrader5 pandas
    python scripts/export_mt5.py --symbol XAUUSD --timeframes M1 M3 M15 H1 --out data/real

LECTURE SEULE : ce script ne contient AUCUN appel d'ordre. La barre en cours de formation est écartée.
Pour obtenir plus d'historique : dans MT5, Outils > Options > Graphiques > « Barres max. dans l'historique » = Illimité,
puis ouvrir un graphique du symbole/timeframe et faire défiler vers la gauche pour que le terminal télécharge l'historique.
Sortie : <SYMBOL>_<TF>.csv (colonnes : time, open, high, low, close, volume, spread, tick_volume, real_volume,
spread_points, time_broker_epoch) + EXPORT-PROVENANCE.json (empreintes SHA-256, couverture, qualité).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

TF_NAMES = ["M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30", "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D1", "W1"]
COLUMNS = ["time", "open", "high", "low", "close", "volume", "spread", "tick_volume", "real_volume", "spread_points", "time_broker_epoch"]


def rates_to_frame(rates, point: float, utc_offset_hours: int = 3) -> pd.DataFrame:
    """Rates MT5 (structured array / liste de dicts) -> DataFrame au format quantbot. `time` n'est qu'une ESTIMATION UTC."""
    df = pd.DataFrame(rates)
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    out = pd.DataFrame({
        "time": pd.to_datetime(df["time"] - utc_offset_hours * 3600, unit="s", utc=True),
        "open": df["open"], "high": df["high"], "low": df["low"], "close": df["close"],
        "volume": df["tick_volume"], "spread": df["spread"] * point, "tick_volume": df["tick_volume"],
        "real_volume": df.get("real_volume", 0), "spread_points": df["spread"], "time_broker_epoch": df["time"]})
    return out[COLUMNS]


def fetch_timeframe(mt5, symbol: str, tf_name: str, max_bars: int, point: float) -> pd.DataFrame:
    tf = getattr(mt5, f"TIMEFRAME_{tf_name}")
    # copy_rates_from_pos(…, 0, n) : position 0 = barre EN FORMATION -> écartée (jamais de décision sur une bougie ouverte)
    rates = mt5.copy_rates_from_pos(symbol, tf, 1, max_bars)
    if rates is None or len(rates) == 0:
        raise SystemExit(f"{symbol} {tf_name} : aucune donnée ({mt5.last_error()}). Augmentez « Barres max. » et ouvrez le graphique.")
    return rates_to_frame(rates, point)


def provenance_entry(df: pd.DataFrame, path: Path, symbol: str, tf: str) -> dict:
    t = pd.to_datetime(df["time"], utc=True)
    step = int(pd.Timedelta(t.diff().median()).total_seconds() // 60) if len(t) > 2 else 0
    return {"symbol": symbol, "timeframe": tf, "rows": int(len(df)), "start": str(t.iloc[0]), "end": str(t.iloc[-1]),
            "span_days": round((t.iloc[-1] - t.iloc[0]).total_seconds() / 86400, 1), "median_step_min": step,
            "duplicate_timestamps": int(df["time_broker_epoch"].duplicated().sum()),
            "invalid_ohlc": int(((df["high"] < df[["open", "close"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1))).sum()),
            "spread_zero_share": round(float((df["spread_points"] == 0).mean()), 4), "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main(argv=None, mt5=None) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--timeframes", nargs="+", default=["M1", "M3", "M15", "H1"])
    ap.add_argument("--bars", type=int, default=200_000, help="nombre maximal de barres par timeframe")
    ap.add_argument("--out", default="data/real")
    ap.add_argument("--terminal", default=None, help="chemin de terminal64.exe (indispensable si deux terminaux MT5 sont installés)")
    args = ap.parse_args(argv)
    bad = [t for t in args.timeframes if t not in TF_NAMES]
    if bad:
        raise SystemExit(f"Timeframes inconnus : {bad}")
    if mt5 is None:
        import MetaTrader5 as mt5  # type: ignore
    if not (mt5.initialize(args.terminal) if args.terminal else mt5.initialize()):
        raise SystemExit(f"initialize() a échoué : {mt5.last_error()}")
    try:
        info = mt5.symbol_info(args.symbol)
        if info is None or not mt5.symbol_select(args.symbol, True):
            raise SystemExit(f"Symbole introuvable : {args.symbol}")
        acct = mt5.account_info()
        out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
        entries = []
        for tf in args.timeframes:
            df = fetch_timeframe(mt5, args.symbol, tf, args.bars, info.point)
            path = out / f"{args.symbol}_{tf}.csv"
            df.to_csv(path, index=False)
            entries.append(provenance_entry(df, path, args.symbol, tf))
            print(f"{tf}: {len(df)} barres, {entries[-1]['start'][:10]} -> {entries[-1]['end'][:10]} ({entries[-1]['span_days']} jours)")
        meta = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "source": f"MetaTrader5 / {getattr(acct, 'server', '?')}",
                "synthetic": False, "orders_sent": 0, "point": info.point, "digits": info.digits, "instruments": entries,
                "clock": {"raw_time_column": "time_broker_epoch", "warning": "`time` = estimation UTC (-3h fixe) ; utiliser time_broker_epoch"},
                "costs": {"spread": "price units = spread_points * point", "commission_swap_slippage": "NON fournis : ne pas supposer zéro"}}
        (out / "EXPORT-PROVENANCE.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
