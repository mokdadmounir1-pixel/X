"""Export d'historique crypto depuis Coinbase (API publique, LECTURE SEULE, sans clé) vers data/crypto/<PRODUIT>_<TF>.csv.

    python scripts/export_coinbase.py --products BTC-USD ETH-USD --timeframes M15 H1 --years 3

Les barres sont en UTC ; la barre en cours est écartée ; un échec réseau est signalé, jamais comblé. Écrit EXPORT-PROVENANCE-COINBASE.json (empreintes SHA-256).
"""
import argparse, hashlib, json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.data.coinbase import GRANULARITY, CoinbaseClient


def main(argv=None, client=None, now=None):
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--products", nargs="+", default=["BTC-USD", "ETH-USD"]); ap.add_argument("--timeframes", nargs="+", default=["M15", "H1"])
    ap.add_argument("--years", type=float, default=3.0); ap.add_argument("--out", default="data/crypto")
    args = ap.parse_args(argv)
    bad = [t for t in args.timeframes if t not in GRANULARITY]
    if bad:
        raise SystemExit(f"Timeframes inconnus : {bad}")
    client = client or CoinbaseClient()
    end = now or datetime.now(timezone.utc); out = Path(args.out); out.mkdir(parents=True, exist_ok=True); entries, failures = [], []
    for p in args.products:
        for tf in args.timeframes:
            try:
                g = GRANULARITY[tf]
                df = client.fetch_range(p, tf, end - timedelta(days=365.25 * args.years), end)
                df = df[df.index + pd.Timedelta(seconds=g) <= pd.Timestamp(end.replace(tzinfo=None))]     # barre en formation écartée
                path = out / f"{p}_{tf}.csv"
                w = df.reset_index(); w["time"] = pd.to_datetime(w["time"]).dt.strftime("%Y-%m-%d %H:%M:%S+00:00"); w.to_csv(path, index=False)
                gaps = df.index.to_series().diff().dt.total_seconds().div(g)
                entries.append({"product": p, "timeframe": tf, "rows": int(len(df)), "start": str(df.index[0]), "end": str(df.index[-1]), "missing_bars": int((gaps[gaps > 1] - 1).sum()),
                                "largest_gap_bars": int(gaps.max()) if len(gaps) else 0, "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
                print(f"{p} {tf}: {len(df)} barres, {entries[-1]['start'][:10]} -> {entries[-1]['end'][:10]}, barres manquantes : {entries[-1]['missing_bars']}")
            except Exception as exc:
                failures.append({"product": p, "timeframe": tf, "reason": f"{type(exc).__name__}: {exc}"}); print(f"{p} {tf}: ÉCHEC {exc}")
    (out / "EXPORT-PROVENANCE-COINBASE.json").write_text(json.dumps({"captured_at_utc": end.isoformat(), "source": "Coinbase Exchange API publique", "synthetic": False,
        "orders_sent": 0, "clock": "UTC natif (pas de décalage de courtier)", "volume": "volume réel (unités de base)", "spread": "non fourni : déclaré dans la spec, jamais supposé nul",
        "instruments": entries, "failures": failures}, indent=1, ensure_ascii=False), encoding="utf-8")
    return 1 if failures and not entries else 0


if __name__ == "__main__":
    sys.exit(main())
