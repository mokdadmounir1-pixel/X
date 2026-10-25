"""Export PROFOND de l'historique MT5 par tranches de dates (copy_rates_range) : remonte aussi loin que le serveur a des données.

    python scripts/export_mt5_deep.py --symbol XAUUSD --timeframes M15 H1 H4 D1 --out data/deep

Pourquoi : copy_rates_from_pos(…, n) plafonne (M15 ≈ 100 000 barres, H4 refuse 1 000 000). Ici on demande des tranches de N jours en
remontant depuis maintenant, on fusionne par époque (sans doublon) et on s'arrête après K tranches vides d'affilée.
LECTURE SEULE : aucun appel d'ordre. La barre la plus récente est écartée (peut être en formation). Écrit les mêmes colonnes que export_mt5.py.
Un échec sur un timeframe n'arrête PAS les autres et n'est jamais masqué : il figure dans EXPORT-PROVENANCE-DEEP.json.
"""
import argparse, importlib.util, json, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
_sp = importlib.util.spec_from_file_location("export_mt5", ROOT / "scripts" / "export_mt5.py")
em = importlib.util.module_from_spec(_sp); _sp.loader.exec_module(em)

CHUNK_DAYS = {"M1": 20, "M3": 45, "M5": 60, "M15": 120, "M30": 240, "H1": 365, "H4": 1460, "D1": 3650}


def deep_rates(mt5, symbol, tf_name, chunk_days, max_empty=3, floor_year=1999, now=None, sleep=time.sleep):
    """Retourne (DataFrame de rates fusionné, notes). Remonte par tranches jusqu'à max_empty tranches vides consécutives."""
    import numpy as np
    tf = getattr(mt5, f"TIMEFRAME_{tf_name}")
    end = now or datetime.now(timezone.utc)
    parts, empty, notes, n_calls = [], 0, [], 0
    while empty < max_empty and end.year >= floor_year:
        start = end - timedelta(days=chunk_days)
        rates = mt5.copy_rates_range(symbol, tf, start, end)
        n_calls += 1
        if rates is None or len(rates) == 0:
            empty += 1
            if rates is None:
                notes.append(f"{start.date()}→{end.date()} : {mt5.last_error()}")
        else:
            empty = 0
            parts.append(pd.DataFrame(rates))
        end = start + timedelta(days=1)          # léger recouvrement ; dédoublonné par époque
        sleep(0.05)
    if not parts:
        return pd.DataFrame(), notes + ["aucune donnée"]
    df = pd.concat(parts).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    return df.iloc[:-1], notes + [f"{n_calls} requêtes"]   # barre la plus récente écartée


def main(argv=None, mt5=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="XAUUSD"); ap.add_argument("--timeframes", nargs="+", default=["M15", "H1", "H4", "D1"])
    ap.add_argument("--out", default="data/deep"); ap.add_argument("--max-empty", type=int, default=3)
    ap.add_argument("--terminal", default=None, help="chemin de terminal64.exe (indispensable si deux terminaux MT5 sont installés)")
    args = ap.parse_args(argv)
    bad = [t for t in args.timeframes if t not in em.TF_NAMES]
    if bad:
        raise SystemExit(f"Timeframes inconnus : {bad}")
    if mt5 is None:
        import MetaTrader5 as mt5  # type: ignore
    if not (mt5.initialize(args.terminal) if args.terminal else mt5.initialize()):
        raise SystemExit(f"initialize() a échoué : {mt5.last_error()}")
    entries, failures = [], []
    try:
        info = mt5.symbol_info(args.symbol)
        if info is None or not mt5.symbol_select(args.symbol, True):
            raise SystemExit(f"Symbole introuvable : {args.symbol}")
        acct = mt5.account_info(); out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
        for tf in args.timeframes:
            try:
                raw, notes = deep_rates(mt5, args.symbol, tf, CHUNK_DAYS.get(tf, 120), args.max_empty)
                if raw.empty:
                    failures.append({"timeframe": tf, "reason": "; ".join(notes)}); print(f"{tf}: AUCUNE DONNÉE ({notes})"); continue
                df = em.rates_to_frame(raw.to_records(index=False), info.point)
                path = out / f"{args.symbol}_{tf}.csv"; df.to_csv(path, index=False)
                e = em.provenance_entry(df, path, args.symbol, tf); e["notes"] = notes; entries.append(e)
                print(f"{tf}: {len(df)} barres, {e['start'][:10]} -> {e['end'][:10]} ({e['span_days']} jours) ; {notes[-1]}")
            except Exception as exc:
                failures.append({"timeframe": tf, "reason": f"{type(exc).__name__}: {exc}"}); print(f"{tf}: ÉCHEC {exc}")
        meta = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "source": f"MetaTrader5 / {getattr(acct, 'server', '?')}", "synthetic": False,
                "orders_sent": 0, "method": "copy_rates_range par tranches", "instruments": entries, "failures": failures,
                "clock": {"raw_time_column": "time_broker_epoch", "warning": "`time` = estimation UTC (-3h fixe) ; utiliser time_broker_epoch"}}
        (out / f"EXPORT-PROVENANCE-DEEP-{args.symbol}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    finally:
        mt5.shutdown()
    return 1 if failures and not entries else 0


if __name__ == "__main__":
    sys.exit(main())
