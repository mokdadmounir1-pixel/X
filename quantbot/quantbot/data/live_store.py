"""Magasin incrémental de barres MT5 CLÔTURÉES, alimenté en continu en LECTURE SEULE (aucun appel d'ordre).

Garanties :
- seules les barres clôturées sont lues (position 1 : la barre en formation n'est jamais stockée) ;
- le fichier ne fait que croître (ajout de barres plus récentes) ; une barre déjà stockée n'est JAMAIS réécrite : si le terminal
  renvoie une valeur différente pour une barre connue, l'écart est consigné (ANOMALIES.jsonl) et rien n'est écrasé ;
- chaque ajout est inscrit dans un journal chaîné par hachage (MANIFEST.jsonl) : toute altération est détectable ;
- le format des colonnes est celui de scripts/export_mt5.py : `load_mt5_csv` lit ces fichiers tels quels.
Les données ajoutées APRÈS la date de gel des specs (data/live/FREEZE.json) forment un échantillon « futur » jamais vu par aucun essai.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

import pandas as pd

COLUMNS = ["time", "open", "high", "low", "close", "volume", "spread", "tick_volume", "real_volume", "spread_points", "time_broker_epoch"]
GENESIS = "0" * 64
TF_SECONDS = {"M1": 60, "M3": 180, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}


def rates_to_frame(rates: Any, point: float, utc_offset_hours: int = 3) -> pd.DataFrame:
    df = pd.DataFrame(rates)
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    out = pd.DataFrame({
        "time": pd.to_datetime(df["time"] - utc_offset_hours * 3600, unit="s", utc=True),
        "open": df["open"], "high": df["high"], "low": df["low"], "close": df["close"], "volume": df["tick_volume"],
        "spread": df["spread"] * point, "tick_volume": df["tick_volume"], "real_volume": df.get("real_volume", 0),
        "spread_points": df["spread"], "time_broker_epoch": df["time"]})
    return out[COLUMNS]


class LiveBarStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / "MANIFEST.jsonl"
        self.anomalies = self.root / "ANOMALIES.jsonl"

    def path(self, symbol: str, tf: str) -> Path:
        return self.root / f"{symbol}_{tf}.csv"

    # --- journal chaîné ---------------------------------------------------------------------------
    def _events(self) -> list[dict]:
        if not self.manifest.exists():
            return []
        return [json.loads(l) for l in self.manifest.read_text(encoding="utf-8").splitlines() if l.strip()]

    @staticmethod
    def _digest(prev: str, body: dict) -> str:
        return hashlib.sha256((prev + json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)).encode()).hexdigest()

    def verify(self) -> bool:
        prev = GENESIS
        for e in self._events():
            body = {k: e[k] for k in e if k not in ("prev", "hash")}
            if e["prev"] != prev or e["hash"] != self._digest(prev, body):
                return False
            prev = e["hash"]
        return True

    def _tail_hash(self) -> str:
        """Hachage du dernier événement SANS relire tout le journal (O(1) amorti) : la fin du fichier est lue ; le journal complet reste vérifiable par `verify`."""
        if not self.manifest.exists() or self.manifest.stat().st_size == 0:
            return GENESIS
        with self.manifest.open("rb") as fh:
            fh.seek(0, 2); size = fh.tell(); fh.seek(max(0, size - 65536))
            lines = [l for l in fh.read().decode("utf-8").splitlines() if l.strip()]
        return json.loads(lines[-1])["hash"]

    def _log(self, body: dict) -> None:
        prev = self._tail_hash()
        body = {**body, "ts": time.time()}
        with self.manifest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**body, "prev": prev, "hash": self._digest(prev, body)}, default=str) + "\n")

    def _anomaly(self, **kw: Any) -> None:
        with self.anomalies.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), **kw}, default=str) + "\n")

    # --- lecture ----------------------------------------------------------------------------------------
    def last_epoch(self, symbol: str, tf: str) -> Optional[int]:
        p = self.path(symbol, tf)
        if not p.exists() or p.stat().st_size == 0:
            return None
        with p.open("rb") as fh:  # dernière ligne sans charger le fichier
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 4096))
            last = fh.read().decode("utf-8").strip().splitlines()[-1]
        return int(last.split(",")[-1])

    # --- mise à jour ----------------------------------------------------------------------------------------
    def update(self, mt5: Any, symbol: str, tf: str, n_bars: int = 1000, max_backfill: int = 100_000) -> dict:
        """Ajoute les barres clôturées plus récentes que la dernière stockée. Retourne un résumé (jamais d'ordre, jamais d'écrasement)."""
        info = mt5.symbol_info(symbol)
        if info is None:
            return {"symbol": symbol, "tf": tf, "status": "symbole_indisponible"}
        tfc = getattr(mt5, f"TIMEFRAME_{tf}")
        last = self.last_epoch(symbol, tf)
        n = n_bars
        while True:
            rates = mt5.copy_rates_from_pos(symbol, tfc, 1, n)   # position 1 : barre en formation exclue
            if rates is None or len(rates) == 0:
                return {"symbol": symbol, "tf": tf, "status": "aucune_donnee", "error": str(mt5.last_error())}
            fr = rates_to_frame(rates, info.point)
            if last is None or int(fr["time_broker_epoch"].iloc[0]) <= last or n >= max_backfill or len(rates) < n:
                break
            n = min(n * 4, max_backfill)                       # la fenêtre ne recouvre pas le stock : on remonte plus loin
        new_mask = fr["time_broker_epoch"] > (last if last is not None else -1)
        overlap = fr[~new_mask]
        res = {"symbol": symbol, "tf": tf, "status": "ok", "appended": int(new_mask.sum()), "bootstrap": last is None}
        if last is not None and len(overlap):                   # cohérence des barres déjà connues
            stored = pd.read_csv(self.path(symbol, tf), usecols=["open", "high", "low", "close", "time_broker_epoch"]).tail(len(overlap) + 5)
            m = overlap.merge(stored, on="time_broker_epoch", suffixes=("", "_s"))
            diff = ((m[["open", "high", "low", "close"]].to_numpy() - m[["open_s", "high_s", "low_s", "close_s"]].to_numpy()) ** 2).sum(axis=1) > 1e-12
            if diff.any():
                bad = m[diff]
                self._anomaly(kind="barre_modifiee", symbol=symbol, tf=tf, epochs=bad["time_broker_epoch"].tolist()[:20])
                res["anomalies"] = int(diff.sum())
        if last is not None and not len(overlap) and len(fr) and int(fr["time_broker_epoch"].iloc[0]) > last:
            self._anomaly(kind="trou_non_comble", symbol=symbol, tf=tf, last_stored=last, first_fetched=int(fr["time_broker_epoch"].iloc[0]))
            res["gap_unfilled"] = True
        add = fr[new_mask]
        if len(add):
            text = add.to_csv(index=False, header=last is None, lineterminator="\n")
            p = self.path(symbol, tf)
            with p.open("a", encoding="utf-8", newline="") as fh:
                fh.write(text)
                fh.flush()
            self._log({"symbol": symbol, "tf": tf, "n": int(len(add)), "first_epoch": int(add["time_broker_epoch"].iloc[0]),
                       "last_epoch": int(add["time_broker_epoch"].iloc[-1]), "rows_sha256": hashlib.sha256(text.encode()).hexdigest()})
        res["last_epoch"] = int(add["time_broker_epoch"].iloc[-1]) if len(add) else last
        return res
