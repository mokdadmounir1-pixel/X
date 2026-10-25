"""Le client HTTP est injecté : AUCUNE requête réseau dans les tests, et le double n'existe que dans ce fichier."""
import ast
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest

from quantbot.data.coinbase import CoinbaseClient, CoinbaseFeed, load_utc_csv, to_frame
from quantbot.exceptions import DataFetchError, DataValidationError

ROOT = Path(__file__).resolve().parents[1]
T0 = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())


def fake_market(n=2000, gran=900, start=T0):
    """Marché de TEST (marche aléatoire déterministe) servi comme l'API Coinbase : [time, low, high, open, close, volume], plus récent d'abord, 300 max."""
    rng = np.random.default_rng(1)
    px = 60000 + np.cumsum(rng.normal(0, 40, n))
    o = np.concatenate([[px[0]], px[:-1]])
    rows = [[start + i * gran, float(min(o[i], px[i]) - 20), float(max(o[i], px[i]) + 25), float(o[i]), float(px[i]), 1.5 + i % 7] for i in range(n)]
    calls = []

    def get(url):
        q = parse_qs(urlparse(url).query); calls.append(url)
        a, b = [int(datetime.fromisoformat(q[k][0].replace("Z", "+00:00")).timestamp()) for k in ("start", "end")]
        out = [r for r in rows if a <= r[0] < b][-300:]
        return 200, json.dumps(out[::-1])
    return rows, get, calls


def test_fetch_range_paginates_and_returns_sorted_unique_utc_bars():
    rows, get, calls = fake_market(1000)
    c = CoinbaseClient(get=get, sleep=lambda _: None)
    df = c.fetch_range("BTC-USD", "M15", datetime.fromtimestamp(T0, timezone.utc), datetime.fromtimestamp(T0 + 1000 * 900, timezone.utc))
    assert len(df) == 1000 and df.index.is_monotonic_increasing and df.index.is_unique and len(calls) == 4
    assert df.index[0] == np.datetime64(T0, "s") and (df["volume"] > 0).all() and (df["spread"] == 0).all()   # spread NON fourni (déclaré dans la spec)


def test_retries_are_bounded_and_429_backs_off_but_400_does_not_retry():
    seq = iter([(429, "slow"), (500, "x"), (200, "[]")]); waits = []
    c = CoinbaseClient(get=lambda u: next(seq), sleep=waits.append, pause=0)
    assert c.candles("BTC-USD", "M15", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc)) == [] and waits[:2] == [1.0, 2.0]
    n = {"c": 0}
    def bad(u):
        n["c"] += 1; return 400, "invalid granularity"
    with pytest.raises(DataFetchError):
        CoinbaseClient(get=bad, sleep=lambda _: None).candles("BTC-USD", "M15", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert n["c"] == 1
    with pytest.raises(DataFetchError):
        CoinbaseClient(get=lambda u: (503, "down"), sleep=lambda _: None, retries=2).candles("BTC-USD", "M15", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))


def test_incoherent_bars_are_refused_not_repaired():
    with pytest.raises(DataValidationError):
        to_frame([[T0, 100.0, 90.0, 95.0, 96.0, 1.0]], 900)                 # high < low


def test_feed_returns_only_closed_bars_and_emits_each_once():
    rows, get, calls = fake_market(1500)
    now = {"t": T0 + 1200 * 900 + 400}                                       # la barre 1200 est EN FORMATION
    feed = CoinbaseFeed("BTC-USD", "M15", n_bars=500, client=CoinbaseClient(get=get, sleep=lambda _: None), clock=lambda: now["t"])
    df = feed.poll()
    assert df.index[-1] == np.datetime64(T0 + 1199 * 900, "s") and len(df) == 500
    assert feed.new_bars(df) == []                                           # démarrage : barre d'histoire non émise
    assert feed.poll() is None                                               # rien de neuf
    now["t"] += 900 * 3
    df2 = feed.poll(); fresh = feed.new_bars(df2)
    assert len(fresh) == 3 and fresh[-1] == np.datetime64(T0 + 1202 * 900, "s") and len(calls) < 10      # incrémental : pas 500 barres à chaque tour
    assert feed.point == 1.0 and feed.source == "Coinbase"


def test_export_writes_loadable_csv_with_provenance_and_reports_failures(tmp_path):
    spec = importlib.util.spec_from_file_location("export_coinbase", ROOT / "scripts" / "export_coinbase.py")
    ec = importlib.util.module_from_spec(spec); spec.loader.exec_module(ec)
    rows, get, calls = fake_market(2000)
    end = datetime.fromtimestamp(T0 + 2000 * 900, timezone.utc)
    client = CoinbaseClient(get=lambda u: get(u) if "BTC-USD" in u else (500, "boom"), sleep=lambda _: None, retries=0)
    rc = ec.main(["--products", "BTC-USD", "ETH-USD", "--timeframes", "M15", "--years", "0.06", "--out", str(tmp_path)], client=client, now=end)
    assert rc == 0
    meta = json.loads((tmp_path / "EXPORT-PROVENANCE-COINBASE.json").read_text(encoding="utf-8"))
    assert meta["orders_sent"] == 0 and len(meta["instruments"]) == 1 and meta["failures"][0]["product"] == "ETH-USD"      # l'échec n'est pas masqué
    df = load_utc_csv(tmp_path / "BTC-USD_M15.csv")
    assert len(df) > 1000 and df.index.is_monotonic_increasing and df.index.tz is None


def test_coinbase_code_has_no_order_or_account_path():
    for f in (ROOT / "quantbot" / "data" / "coinbase.py", ROOT / "scripts" / "export_coinbase.py"):
        src = f.read_text(encoding="utf-8")
        assert "/orders" not in src and "api_key" not in src.lower() and "CB-ACCESS" not in src and "POST" not in src
        assert not {n.func.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)} & {"post", "put", "delete"}
