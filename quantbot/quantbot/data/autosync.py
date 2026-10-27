"""Synchronisation AUTOMATIQUE des données du terminal, en lecture seule, sans clé :

- Coinbase (API publique) : barres clôturées BTC-USD/ETH-USD -> data/crypto/<PRODUIT>_<TF>.csv, ajout incrémental (jamais de barre réécrite) ;
- MetaTrader 5 (si le module et un terminal DÉMO sont disponibles) : data/live/ via LiveBarStore (chaîne de hachage).
Un échec réseau ou un terminal absent est RAPPORTÉ (data/sync_status.json) et réessayé ; rien n'est jamais comblé ni inventé. Aucun ordre.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from ..filelock import exclusive_lock
from .coinbase import GRANULARITY, CoinbaseClient, load_utc_csv

DEFAULTS = {"coinbase": {"products": ["BTC-USD", "ETH-USD"], "timeframes": ["M15"], "initial_days": 90},
            "mt5": {"symbols": ["XAUUSD", "XAGUSD", "EURUSD", "USTEC", "USDX", "DXY", "USDIDX"], "timeframes": ["M1", "M5", "M15", "H1"], "bars": 1000, "bootstrap_bars": 50000,
                    "terminal": r"C:\Program Files\MetaTrader 5\terminal64.exe", "depth_symbol": "XAUUSD", "depth_levels": 5, "depth_interval_s": 2.0},
            "interval_s": 300}


def sync_coinbase(root: Path, products, timeframes, initial_days: int = 90, client=None, now: datetime | None = None) -> list[dict]:
    client = client or CoinbaseClient(); now = now or datetime.now(timezone.utc); out = []
    d = Path(root) / "data" / "crypto"; d.mkdir(parents=True, exist_ok=True)
    for p in products:
        for tf in timeframes:
            g = GRANULARITY[tf]; path = d / f"{p}_{tf}.csv"; rec = {"source": "coinbase", "product": p, "tf": tf}
            try:
                old = load_utc_csv(path) if path.exists() else None
                start = (old.index[-1] + pd.Timedelta(seconds=g)).to_pydatetime().replace(tzinfo=timezone.utc) if old is not None and len(old) else now - timedelta(days=initial_days)
                new = client.fetch_range(p, tf, start, now)
                new = new[new.index + pd.Timedelta(seconds=g) <= pd.Timestamp(now.replace(tzinfo=None))]       # barre en formation écartée
                if old is not None:
                    new = new[new.index > old.index[-1]]
                if len(new):
                    df = new if old is None else pd.concat([old, new])
                    w = df.reset_index(); w["time"] = pd.to_datetime(w["time"]).dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
                    tmp = path.with_suffix(".tmp"); w.to_csv(tmp, index=False); tmp.replace(path)
                rec.update(status="ok", appended=int(len(new)), last_bar=str((new.index[-1] if len(new) else old.index[-1]) if (len(new) or old is not None) else None))
            except Exception as exc:                      # réseau coupé, API indisponible : on le dit, on réessaiera
                rec.update(status="erreur", error=f"{type(exc).__name__}: {exc}"[:300])
            out.append(rec)
    return out


def sync_mt5(root: Path, cfg: dict, mt5=None, shutdown: bool = True) -> dict:
    if mt5 is None:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError:
            return {"source": "mt5", "status": "indisponible", "note": "module MetaTrader5 absent (Windows + pip install MetaTrader5)"}
    from .live_store import LiveBarStore
    from ..live.symbols import maybe_alias
    try:
        if not mt5.initialize(cfg["terminal"], timeout=15000):
            return {"source": "mt5", "status": "terminal_injoignable", "note": str(mt5.last_error())}
        acct, term = mt5.account_info(), mt5.terminal_info()
        if acct is None or term is None or not term.connected:
            return {"source": "mt5", "status": "deconnecte"}
        if acct.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            return {"source": "mt5", "status": "refuse", "note": "compte non démo : aucune lecture"}
        try:                                   # un seul écrivain sur data/live (le démon autonome tient le même verrou)
            with exclusive_lock(Path(root) / "data" / "live" / "daemon.lock"):
                return _sync_series(maybe_alias(mt5, root), LiveBarStore(Path(root) / "data" / "live"), cfg)
        except RuntimeError:
            return {"source": "mt5", "status": "verrou_occupe", "note": "data_daemon.py écrit déjà dans data/live : un seul écrivain à la fois"}
    finally:
        if shutdown:
            try:
                mt5.shutdown()
            except Exception:
                pass


def _sync_series(mt5, store, cfg) -> dict:
    series = []
    for s in cfg["symbols"]:
        if not mt5.symbol_select(s, True):
            series.append({"symbol": s, "status": "symbole_indisponible"}); continue
        for tf in cfg["timeframes"]:
            try:
                series.append(store.update(mt5, s, tf, cfg["bootstrap_bars"] if store.last_epoch(s, tf) is None else cfg["bars"]))
            except Exception as exc:
                series.append({"symbol": s, "tf": tf, "status": "erreur", "error": f"{type(exc).__name__}: {exc}"[:300]})
    return {"source": "mt5", "status": "ok", "series": series, "chain_ok": store.verify()}


def sync_external(root: Path, get=None, fred_key: str | None = None, now: float | None = None) -> list[dict]:
    """COT or (CFTC, gratuit) -> data/external/cot_gold.csv ; releases FRED -> data/external/macro_events.csv SI une clé gratuite est fournie (FRED_API_KEY). Échec = rapporté, jamais comblé."""
    from .external import _get, cot_percentile, fetch_cot, fetch_fred_releases
    get = get or _get; d = Path(root) / "data" / "external"; d.mkdir(parents=True, exist_ok=True); out = []
    try:
        cot = fetch_cot(get); cot["percentile_156w"] = cot_percentile(cot); cot.to_csv(d / "cot_gold.csv")
        out.append({"source": "cot", "status": "ok", "rows": int(len(cot)), "last_report": str(cot["report_date"].iloc[-1].date())})
    except Exception as exc:
        out.append({"source": "cot", "status": "erreur", "error": f"{type(exc).__name__}: {exc}"[:200]})
    if fred_key:
        try:
            ev = fetch_fred_releases(fred_key, (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"), (datetime.now(timezone.utc) + timedelta(days=365)).strftime("%Y-%m-%d"), get)
            ev.to_csv(d / "macro_events.csv", index=False); out.append({"source": "fred", "status": "ok", "rows": int(len(ev))})
        except Exception as exc:
            out.append({"source": "fred", "status": "erreur", "error": f"{type(exc).__name__}: {str(exc)[:80]}"})
    else:
        out.append({"source": "fred", "status": "non_configure", "note": "clé gratuite FRED absente (variable FRED_API_KEY) : calendrier limité aux règles régulières (NFP)"})
    return out


def sample_ticks(mt5, root: Path, symbol: str, max_ticks: int = 100_000) -> dict:
    """Ticks RÉELS (bid/ask/last/volume/flags en ms) ajoutés à data/live/ticks/<SYMBOLE>_<AAAAMMJJ>.csv, curseur par time_msc (aucun tick réécrit, aucun doublon).
    Nécessaire à tout calcul intra-barre (flux de cotations, spread instantané) : les barres ne suffisent pas."""
    try:
        d = Path(root) / "data" / "live" / "ticks"; d.mkdir(parents=True, exist_ok=True); cur = d / f"_cursor_{symbol}.json"
        last = json.loads(cur.read_text())["time_msc"] if cur.exists() else None
        start = datetime.fromtimestamp((last / 1000.0) if last else time.time() - 600, timezone.utc)
        ticks = mt5.copy_ticks_from(symbol, start, max_ticks, getattr(mt5, "COPY_TICKS_ALL", -1))
        if ticks is None or len(ticks) == 0:
            return {"status": "aucun_tick", "error": str(mt5.last_error()) if hasattr(mt5, "last_error") else ""}
        df = pd.DataFrame(ticks)
        if last:
            df = df[df["time_msc"] > last]
        if df.empty:
            return {"status": "ok", "appended": 0}
        df = df.drop_duplicates("time_msc").sort_values("time_msc"); cols = [c for c in ("time_msc", "bid", "ask", "last", "volume", "flags") if c in df.columns]
        for day, g in df.groupby(pd.to_datetime(df["time_msc"], unit="ms", utc=True).dt.strftime("%Y%m%d")):
            f = d / f"{symbol}_{day}.csv"; g[cols].to_csv(f, mode="a", header=not f.exists(), index=False)
        cur.write_text(json.dumps({"time_msc": int(df["time_msc"].iloc[-1])}))
        return {"status": "ok", "appended": int(len(df)), "last_time_msc": int(df["time_msc"].iloc[-1])}
    except Exception as exc:
        return {"status": "erreur", "error": f"{type(exc).__name__}: {exc}"[:200]}


def sample_depth(mt5, root: Path, symbol: str, levels: int = 5, now: float | None = None) -> dict:
    """UN instantané de profondeur (market_book) ajouté à data/live/depth/<SYMBOLE>_<AAAAMMJJ>.jsonl : tailles bid/ask des `levels` meilleurs niveaux, nécessaires à un VRAI OFI.
    Si le courtier n'expose pas la profondeur, on le dit (status) et on n'écrit rien."""
    try:
        if not mt5.market_book_add(symbol):
            return {"status": "carnet_indisponible", "note": "le courtier n'expose pas la profondeur de marché pour ce symbole"}
        book = mt5.market_book_get(symbol)
        if not book:
            return {"status": "carnet_vide"}
        bids = sorted((b for b in book if b.type == getattr(mt5, "BOOK_TYPE_BUY", 2)), key=lambda b: -b.price)[:levels]
        asks = sorted((b for b in book if b.type == getattr(mt5, "BOOK_TYPE_SELL", 1)), key=lambda b: b.price)[:levels]
        if not bids or not asks:
            return {"status": "carnet_incomplet"}
        t = time.time() if now is None else now; d = Path(root) / "data" / "live" / "depth"; d.mkdir(parents=True, exist_ok=True)
        rec = {"t": t, "bids": [[float(b.price), float(b.volume)] for b in bids], "asks": [[float(a.price), float(a.volume)] for a in asks]}
        with (d / f"{symbol}_{datetime.fromtimestamp(t, timezone.utc):%Y%m%d}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "erreur", "error": f"{type(exc).__name__}: {exc}"[:200]}


class AutoSync:
    """Thread démon : un passage tout de suite, puis toutes les `interval_s` secondes. Écrit data/sync_status.json (lu par le terminal)."""

    def __init__(self, root: Path, cfg: dict | None = None, client=None, mt5=None, mt5_enabled: bool = True) -> None:
        self.root, self.client, self.mt5, self.mt5_enabled = Path(root), client, mt5, mt5_enabled
        self.cfg = {**DEFAULTS, **(cfg or {})}; self._stop = threading.Event(); self.cycles = 0; self._mt5_ok = False; self.depth_status: dict = {}; self.tick_status: dict = {}; self.clock: dict = {}; self._clock_at = 0.0; self.external: list = []; self._ext_at = 0.0

    def run_once(self) -> dict:
        res = []
        cb = self.cfg["coinbase"]
        res += sync_coinbase(self.root, cb["products"], cb["timeframes"], cb["initial_days"], self.client)
        if self.mt5_enabled:
            r = sync_mt5(self.root, self.cfg["mt5"], self.mt5, shutdown=False); res.append(r)
            self._mt5_ok = r.get("status") == "ok"
            if self._mt5_ok:
                m = self.cfg["mt5"]; mt5m = self.mt5
                if mt5m is None:
                    import MetaTrader5 as mt5m  # type: ignore
                self.tick_status = sample_ticks(mt5m, self.root, m["depth_symbol"])
        if time.time() - self._clock_at > 3600:       # contrôle NTP au plus une fois par heure
            from ..clock import clock_health, clock_offset
            self.clock = clock_offset(); self.clock["health"] = clock_health(self.clock); self._clock_at = time.time()
        if time.time() - self._ext_at > 6 * 3600:          # données externes : au plus toutes les 6 h
            self.external = sync_external(self.root, fred_key=os.environ.get("FRED_API_KEY")); self._ext_at = time.time()
        res += self.external
        self.cycles += 1
        st = {"ts": time.time(), "cycle": self.cycles, "interval_s": self.cfg["interval_s"], "results": res, "depth": self.depth_status, "ticks": self.tick_status, "clock": self.clock, "orders_sent": 0}
        try:
            (self.root / "data").mkdir(parents=True, exist_ok=True); (self.root / "data" / "sync_status.json").write_text(json.dumps(st, indent=1, default=str), encoding="utf-8")
        except OSError:
            pass
        return st

    def start(self) -> threading.Thread:
        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.run_once()
                except Exception:                        # le thread ne meurt jamais : prochain passage
                    pass
                self._wait_with_depth()
        t = threading.Thread(target=loop, daemon=True, name="quantbot-autosync"); t.start(); return t

    def _wait_with_depth(self) -> None:
        """Attend le prochain passage ; si MT5 est connecté, échantillonne la profondeur du carnet toutes les `depth_interval_s` secondes (même thread : le module MT5 n'est pas thread-safe)."""
        end = time.time() + self.cfg["interval_s"]; m = self.cfg["mt5"]; mt5 = self.mt5
        if mt5 is None and self._mt5_ok:
            import MetaTrader5 as mt5  # type: ignore
        while not self._stop.is_set() and time.time() < end:
            if self.mt5_enabled and self._mt5_ok and mt5 is not None:
                self.depth_status = sample_depth(mt5, self.root, m["depth_symbol"], m["depth_levels"])
                if self.depth_status["status"] in ("carnet_indisponible", "carnet_vide", "carnet_incomplet", "erreur"):
                    self._stop.wait(min(60.0, max(1.0, end - time.time()))); continue      # pas de profondeur : inutile d'insister chaque seconde
            self._stop.wait(m["depth_interval_s"] if self._mt5_ok else min(5.0, max(0.1, end - time.time())))

    def stop(self) -> None:
        self._stop.set()
