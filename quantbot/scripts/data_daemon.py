"""Démon d'extraction MT5 : met à jour data/live/<SYMBOLE>_<TF>.csv en continu, en LECTURE SEULE (aucun appel d'ordre).

    python scripts/data_daemon.py --symbols XAUUSD EURUSD USTEC --timeframes M15 H1 --interval 30

- compte démo exigé ; terminal déconnecté ou marché fermé = on attend, on ne plante pas, on n'invente rien ;
- écrit data/live/DAEMON_STATUS.json à chaque passage (lu par l'interface) ;
- un seul démon par dossier (verrou) ; Ctrl+C = arrêt propre.
"""
import argparse, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.data.live_store import LiveBarStore
from quantbot.filelock import exclusive_lock


def cycle(mt5, store, symbols, tfs, n_bars):
    acct, term = mt5.account_info(), mt5.terminal_info()
    if acct is None or term is None or not term.connected:
        return {"connected": False, "series": [], "note": "terminal déconnecté : nouvelle tentative au prochain passage"}
    if acct.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        return {"connected": True, "refused": "compte non démo : le démon refuse de lire", "series": []}
    series = []
    for s in symbols:
        if not mt5.symbol_select(s, True):
            series.append({"symbol": s, "status": "symbole_indisponible"}); continue
        for tf in tfs:
            try:
                series.append(store.update(mt5, s, tf, n_bars))
            except Exception as exc:  # une série en panne n'arrête pas les autres
                series.append({"symbol": s, "tf": tf, "status": "erreur", "error": f"{type(exc).__name__}: {exc}"})
    return {"connected": True, "series": series}


def main(argv=None, mt5=None, sleep=time.sleep, max_cycles=None):
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="+", default=["XAUUSD"]); ap.add_argument("--timeframes", nargs="+", default=["M15"])
    ap.add_argument("--interval", type=float, default=30.0); ap.add_argument("--bars", type=int, default=1000)
    ap.add_argument("--out", default=str(ROOT / "data" / "live")); ap.add_argument("--terminal", default=r"C:\Program Files\MetaTrader 5\terminal64.exe")
    args = ap.parse_args(argv)
    if not 1 <= args.interval <= 3600:
        ap.error("--interval entre 1 et 3600 s")
    store = LiveBarStore(args.out); status_path = Path(args.out) / "DAEMON_STATUS.json"
    if mt5 is None:
        import MetaTrader5 as mt5  # type: ignore
    n, initialized = 0, False
    try:
        with exclusive_lock(Path(args.out) / "daemon.lock"):
            while max_cycles is None or n < max_cycles:
                n += 1
                if not initialized:
                    initialized = bool(mt5.initialize(args.terminal, timeout=15000))
                if initialized:
                    st = cycle(mt5, store, args.symbols, args.timeframes, args.bars)
                else:
                    st = {"connected": False, "series": [], "note": f"initialize() a échoué : {mt5.last_error()}"}
                st.update(ts=time.time(), cycle=n, chain_ok=store.verify(), orders_sent=0)
                status_path.write_text(json.dumps(st, default=str, indent=1), encoding="utf-8")
                print(json.dumps({"cycle": n, "connected": st["connected"], "appended": sum(x.get("appended", 0) for x in st["series"])}), flush=True)
                if max_cycles is None or n < max_cycles:
                    sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        if initialized:
            mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
