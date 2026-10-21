"""Chargement des données : MT5 (priorité 1), CSV (2), ccxt crypto (3), synthétique (4).
Tout est converti en UTC ; `df.attrs['source']` trace l'origine (affichée partout)."""
from __future__ import annotations
import hashlib
import io
from pathlib import Path
import numpy as np
import pandas as pd

COLS = ["open", "high", "low", "close", "volume", "spread"]


def data_hash(dfs: dict[str, pd.DataFrame]) -> str:
    h = hashlib.sha256()
    for k in sorted(dfs):
        d = dfs[k]
        h.update(k.encode()); h.update(str(len(d)).encode())
        h.update(np.ascontiguousarray(d[["open", "high", "low", "close"]].to_numpy("float64")).tobytes())
        h.update(str(d.index[0]).encode()); h.update(str(d.index[-1]).encode())
    return h.hexdigest()[:16]


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: str(c).strip().lower().replace("<", "").replace(">", "") for c in df.columns})
    ren = {"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume", "tick_volume": "volume",
           "tickvol": "volume", "real_volume": "volume", "gmt time": "time", "timestamp": "time",
           "datetime": "time", "date": "time", "local time": "time"}
    return df.rename(columns={k: v for k, v in ren.items() if k in df.columns})


def load_csv(path: str, tz: str | None = None, side: str = "bid", instrument: str = "") -> pd.DataFrame:
    """CSV générique (Dukascopy, MT5 export, etc.). Détecte séparateur, colonnes, fuseau et
    côté bid/ask. `tz` force le fuseau source ; sinon UTC supposé sauf indication « GMT+x »."""
    raw = Path(path).read_text(errors="ignore")
    head = raw[:2000]
    sep = max([",", ";", "\t"], key=head.count)
    df = pd.read_csv(io.StringIO(raw), sep=sep)
    df = _norm_cols(df)
    if "time" not in df.columns and {"date", "time"} <= set(df.columns):
        pass
    if "time" not in df.columns:  # MT5 : <DATE> <TIME> séparés
        if "date" in df.columns:
            df["time"] = df["date"].astype(str)
    if "date" in df.columns and "time" in df.columns and df["time"].astype(str).str.len().max() <= 8:
        df["time"] = df["date"].astype(str) + " " + df["time"].astype(str)
    t = pd.to_datetime(df["time"], utc=False, errors="coerce", dayfirst=("." in str(df["time"].iloc[0])[:5] and
                       str(df["time"].iloc[0])[2] == "."))
    src_tz = tz
    if src_tz is None:
        s = str(df["time"].iloc[0])
        src_tz = "UTC"
        if "GMT" in s and ("+" in s[-5:] or "-" in s[-5:]):
            src_tz = "UTC"
    if t.dt.tz is None:
        t = t.dt.tz_localize(src_tz, ambiguous="infer", nonexistent="shift_forward") if src_tz != "UTC" \
            else t.dt.tz_localize("UTC")
    df.index = t.dt.tz_convert("UTC")
    for c in ("open", "high", "low", "close"):
        if c not in df.columns:
            raise ValueError(f"colonne {c} introuvable dans {path} (colonnes: {list(df.columns)})")
    if "volume" not in df.columns:
        df["volume"] = 0
    if side == "ask" or "ask" in Path(path).name.lower():
        side = "ask"
    out = df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()
    out = out[~out.index.duplicated(keep="first")]
    out.index.name = "time"
    out.attrs.update(source=f"CSV:{Path(path).name}", side=side, instrument=instrument, src_tz=src_tz)
    return out


def merge_bid_ask(bid: pd.DataFrame, ask: pd.DataFrame) -> pd.DataFrame:
    """Combine deux CSV bid/ask : prix = BID, colonne spread = ask_close - bid_close mesuré."""
    j = bid.join(ask[["close"]].rename(columns={"close": "ask_close"}), how="inner")
    out = bid.loc[j.index].copy()
    out["spread"] = (j["ask_close"] - j["close"]).clip(lower=0)
    out.attrs.update(bid.attrs)
    return out


def load_mt5(symbol: str, start, end, timeframe: str = "M5", server_utc_offset_h: float | None = None) -> pd.DataFrame:
    """Export MT5 via le package MetaTrader5 (à exécuter sur la machine de l'utilisateur).
    Les timestamps MT5 sont en heure serveur : on retire le décalage fourni ou détecté."""
    import MetaTrader5 as mt5  # import tardif : dépendance optionnelle
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() a échoué : {mt5.last_error()}")
    tf = getattr(mt5, "TIMEFRAME_" + timeframe)
    rates = mt5.copy_rates_range(symbol, tf, pd.Timestamp(start).to_pydatetime(), pd.Timestamp(end).to_pydatetime())
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"aucune donnée MT5 pour {symbol} : {mt5.last_error()}")
    df = pd.DataFrame(rates)
    if server_utc_offset_h is None:
        tick = mt5.symbol_info_tick(symbol)
        server_utc_offset_h = round((tick.time - pd.Timestamp.utcnow().timestamp()) / 3600) if tick else 0
    t = pd.to_datetime(df["time"], unit="s") - pd.Timedelta(hours=server_utc_offset_h)
    pt = mt5.symbol_info(symbol).point
    out = pd.DataFrame({"open": df.open, "high": df.high, "low": df.low, "close": df.close,
                        "volume": df.tick_volume, "spread": df.spread * pt}).set_index(t.dt.tz_localize("UTC"))
    out.index.name = "time"
    out.attrs.update(source=f"MT5:{symbol}", side="bid", instrument=symbol)
    return out


def specs_from_mt5(name: str, symbol: str):
    """Construit un Spec depuis symbol_info() du courtier (remplace les défauts [HYPOTHÈSE])."""
    import MetaTrader5 as mt5
    from dataclasses import replace
    from ..instruments import SPECS
    si = mt5.symbol_info(symbol)
    base = SPECS[name]
    return replace(base, min_lot=si.volume_min, lot_step=si.volume_step, max_lot=si.volume_max,
                   usd_per_unit=si.trade_tick_value / si.trade_tick_size, tick=si.trade_tick_size)


def load_ccxt(symbol="BTC/USDT", exchanges=("binance", "bybit", "kraken"), timeframe="5m",
              since=None, cache_dir="data_cache", limit=1000) -> pd.DataFrame:
    """Crypto uniquement : pagination + cache disque, bascule d'exchange en cas d'échec."""
    import ccxt  # optionnel
    cache = Path(cache_dir); cache.mkdir(exist_ok=True)
    f = cache / f"{symbol.replace('/', '')}_{timeframe}.parquet"
    last_err = None
    for ex_id in exchanges:
        try:
            ex = getattr(ccxt, ex_id)({"enableRateLimit": True})
            ms = int(pd.Timestamp(since or "2021-01-01", tz="UTC").timestamp() * 1000)
            rows = []
            while True:
                b = ex.fetch_ohlcv(symbol, timeframe, since=ms, limit=limit)
                if not b:
                    break
                rows += b; ms = b[-1][0] + 1
                if len(b) < limit:
                    break
            df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"])
            df.index = pd.to_datetime(df.pop("t"), unit="ms", utc=True)
            df.index.name = "time"; df = df[~df.index.duplicated()]
            try:
                df.to_parquet(f)
            except Exception:
                pass
            df.attrs.update(source=f"CCXT:{ex_id}:{symbol}", side="mid", instrument="BTCUSD")
            return df
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"ccxt: tous les exchanges ont échoué ({last_err})")


def load_dir(directory: str, tz: str | None = None) -> dict[str, pd.DataFrame]:
    """Charge tous les CSV d'un dossier ; le nom du fichier (avant '_') donne l'instrument."""
    out = {}
    for p in sorted(Path(directory).glob("*.csv")):
        name = p.stem.split("_")[0].upper()
        out[name] = load_csv(str(p), tz=tz, instrument=name)
    return out


def get_universe(args) -> dict[str, pd.DataFrame]:
    """Sélection par priorité. Retourne toujours des frames dont attrs['source'] dit la vérité."""
    names = [n.strip() for n in args.instruments.split(",")]
    if getattr(args, "data_dir", None):
        d = load_dir(args.data_dir, getattr(args, "tz", None))
        return {k: v for k, v in d.items() if k in names or not names}
    if getattr(args, "mt5", False):
        return {n: load_mt5(n, args.start, args.end, args.timeframe) for n in names}
    from .synth import make_universe
    return make_universe(names, seed=args.seed, years=args.years, persistence=getattr(args, "persistence", 0.0))
