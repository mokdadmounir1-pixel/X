"""Synchronisation AUTOMATIQUE des données du terminal, en lecture seule, sans clé :

- Coinbase (API publique) : barres clôturées BTC-USD/ETH-USD -> data/crypto/<PRODUIT>_<TF>.csv, ajout incrémental (jamais de barre réécrite) ;
- MetaTrader 5 (si le module et un terminal DÉMO sont disponibles) : data/live/ via LiveBarStore (chaîne de hachage).
Un échec réseau ou un terminal absent est RAPPORTÉ (data/sync_status.json) et réessayé ; rien n'est jamais comblé ni inventé. Aucun ordre.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .coinbase import GRANULARITY, CoinbaseClient, load_utc_csv

DEFAULTS = {"coinbase": {"products": ["BTC-USD", "ETH-USD"], "timeframes": ["M15"], "initial_days": 90},
            "mt5": {"symbols": ["XAUUSD", "EURUSD", "USTEC"], "timeframes": ["M15"], "bars": 1000, "terminal": r"C:\Program Files\MetaTrader 5\terminal64.exe"},
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


def sync_mt5(root: Path, cfg: dict, mt5=None) -> dict:
    if mt5 is None:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError:
            return {"source": "mt5", "status": "indisponible", "note": "module MetaTrader5 absent (Windows + pip install MetaTrader5)"}
    from .live_store import LiveBarStore
    try:
        if not mt5.initialize(cfg["terminal"], timeout=15000):
            return {"source": "mt5", "status": "terminal_injoignable", "note": str(mt5.last_error())}
        acct, term = mt5.account_info(), mt5.terminal_info()
        if acct is None or term is None or not term.connected:
            return {"source": "mt5", "status": "deconnecte"}
        if acct.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            return {"source": "mt5", "status": "refuse", "note": "compte non démo : aucune lecture"}
        store = LiveBarStore(Path(root) / "data" / "live"); series = []
        for s in cfg["symbols"]:
            if not mt5.symbol_select(s, True):
                series.append({"symbol": s, "status": "symbole_indisponible"}); continue
            for tf in cfg["timeframes"]:
                try:
                    series.append(store.update(mt5, s, tf, cfg["bars"]))
                except Exception as exc:
                    series.append({"symbol": s, "tf": tf, "status": "erreur", "error": f"{type(exc).__name__}: {exc}"[:300]})
        return {"source": "mt5", "status": "ok", "series": series, "chain_ok": store.verify()}
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass


class AutoSync:
    """Thread démon : un passage tout de suite, puis toutes les `interval_s` secondes. Écrit data/sync_status.json (lu par le terminal)."""

    def __init__(self, root: Path, cfg: dict | None = None, client=None, mt5=None, mt5_enabled: bool = True) -> None:
        self.root, self.client, self.mt5, self.mt5_enabled = Path(root), client, mt5, mt5_enabled
        self.cfg = {**DEFAULTS, **(cfg or {})}; self._stop = threading.Event(); self.cycles = 0

    def run_once(self) -> dict:
        res = []
        cb = self.cfg["coinbase"]
        res += sync_coinbase(self.root, cb["products"], cb["timeframes"], cb["initial_days"], self.client)
        if self.mt5_enabled:
            res.append(sync_mt5(self.root, self.cfg["mt5"], self.mt5))
        self.cycles += 1
        st = {"ts": time.time(), "cycle": self.cycles, "interval_s": self.cfg["interval_s"], "results": res, "orders_sent": 0}
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
                self._stop.wait(self.cfg["interval_s"])
        t = threading.Thread(target=loop, daemon=True, name="quantbot-autosync"); t.start(); return t

    def stop(self) -> None:
        self._stop.set()
