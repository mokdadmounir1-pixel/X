"""Simulation PAPER permanente : toutes les stratégies préenregistrées tournent sur les barres RÉELLES, avec des trades SIMULÉS.

    python scripts/paper_all.py --terminal "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

- une base d'état par couple (instrument, stratégie) dans runtime/paper/ ; l'interface (onglet « Simulation ») les agrège ;
- AUCUNE approbation n'est lue et AUCUN broker d'ordres n'est construit : force_observation=True (PaperBroker uniquement) ;
- compte démo exigé ; MT5 n'est utilisé qu'en lecture (barres, symbole) ; terminal déconnecté = on attend ;
- ces trades simulés ne sont PAS une validation : prix réels, exécutions et PnL simulés.
"""
import argparse, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.filelock import exclusive_lock
from quantbot.live.runner import LiveRunner


def combos(spec: dict, symbols=None, strategies=None):
    out = []
    for name, scfg in spec["strategies"].items():
        for inst in scfg["instruments"]:
            if (not symbols or inst in symbols) and (not strategies or name in strategies):
                out.append((inst, name))
    return out


def build_runners(mt5, spec_path, out_dir, pairs, timeframe="M15", clock=time.time, feed_factory=None):
    runners, errors = [], []
    for inst, name in pairs:
        try:
            r = LiveRunner(mt5, inst, name, spec_path, approvals_path=out_dir / "NO_APPROVALS_READ.json", state_path=out_dir / f"{inst}_{name}.db",
                           kill_file=out_dir / "KILL", timeframe=timeframe, clock=clock, force_observation=True,
                           feed=feed_factory(inst) if feed_factory else None)
            r.setup()
            assert r.mode == "OBSERVATION"
            runners.append(r)
        except Exception as exc:   # un couple en échec n'arrête pas les autres, et l'échec est visible
            errors.append({"instrument": inst, "strategy": name, "error": f"{type(exc).__name__}: {exc}"})
    return runners, errors


def main(argv=None, mt5=None, sleep=time.sleep, max_cycles=None, coinbase_client=None):
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", default="specs/inst_strategies_v1.json"); ap.add_argument("--out", default="runtime/paper")
    ap.add_argument("--symbols", nargs="+"); ap.add_argument("--strategies", nargs="+"); ap.add_argument("--poll", type=float, default=10.0)
    ap.add_argument("--terminal", default=None)
    ap.add_argument("--source", choices=["mt5", "coinbase"], default="mt5", help="coinbase : crypto via l'API publique (lecture seule, sans clé, sans MT5)")
    ap.add_argument("--client", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.source == "coinbase" and args.spec == "specs/inst_strategies_v1.json":
        args.spec = "specs/crypto_paper_v1.json"
    out_dir = (ROOT / args.out).resolve(); out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = ROOT / args.spec; spec = json.loads(spec_path.read_text(encoding="utf-8"))
    feed_factory = None
    if args.source == "coinbase":
        from quantbot.data.coinbase import CoinbaseFeed
        feed_factory = lambda inst: CoinbaseFeed(inst, "M15", client=coinbase_client)
        mt5 = None
    else:
        if mt5 is None:
            import MetaTrader5 as mt5  # type: ignore
        if not (mt5.initialize(args.terminal, timeout=15000) if args.terminal else mt5.initialize()):
            print(json.dumps({"erreur": f"initialize() a échoué : {mt5.last_error()}"}, ensure_ascii=False)); return 1
    n = 0
    try:
        if mt5 is not None:
            acct = mt5.account_info()
            if acct is None or acct.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
                print(json.dumps({"erreur": "compte démo non confirmé : simulation refusée"}, ensure_ascii=False)); return 1
        with exclusive_lock(out_dir / "paper.lock"):
            runners, errors = build_runners(mt5, spec_path, out_dir, combos(spec, args.symbols, args.strategies), feed_factory=feed_factory)
            (out_dir / "STATUS.json").write_text(json.dumps({"runners": [f"{r.symbol}_{r.strategy_id}" for r in runners], "errors": errors, "started": time.time(), "source": args.source}, indent=1), encoding="utf-8")
            print(json.dumps({"runners": len(runners), "errors": errors}, ensure_ascii=False), flush=True)
            while max_cycles is None or n < max_cycles:
                n += 1
                for r in runners:
                    r.step()
                if max_cycles is None or n < max_cycles:
                    sleep(args.poll)
    except KeyboardInterrupt:
        pass
    finally:
        if mt5 is not None:
            mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
