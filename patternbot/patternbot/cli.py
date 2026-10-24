"""Interface en ligne de commande : python -m patternbot <commande>."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ai.adapters import build_adapters
from .ai.orchestrator import AIOrchestrator
from .backtest.engine import Backtester
from .config import Settings, load_settings, save_settings
from .data.loaders import fetch_ccxt, fetch_mt5, generate_synthetic, load_csv
from .exceptions import PatternBotError
from .improvement.loop import ImprovementLoop
from .improvement.runner import PaperRunner
from .logging_utils import setup_logging
from .memory.store import ExperimentStore
from .signals.engine import SignalEngine
from .validation.validator import Validator


def _load_data(args, settings: Settings):
    if args.csv:
        return load_csv(args.csv, repair=True)
    if args.exchange:
        return fetch_ccxt(args.exchange, args.symbol or settings.execution.symbol, settings.execution.timeframe)
    if args.mt5:
        return fetch_mt5(args.mt5)
    return generate_synthetic(n=args.bars, seed=args.seed)


def _add_data_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config")
    p.add_argument("--csv")
    p.add_argument("--exchange", help="id ccxt, ex: binance")
    p.add_argument("--symbol")
    p.add_argument("--mt5", help="symbole MetaTrader 5 (Windows)")
    p.add_argument("--bars", type=int, default=1500, help="taille des données synthétiques")
    p.add_argument("--seed", type=int, default=7)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser("patternbot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init-config"); p.add_argument("path", nargs="?", default="config/default.json")
    for name in ("scan", "backtest", "validate", "improve"):
        _add_data_args(sub.add_parser(name))
    sub.choices["improve"].add_argument("--db", default="patternbot.db")
    sub.choices["improve"].add_argument("--use-ai", action="store_true")
    run = sub.add_parser("run-paper", help="trader en paper trading qui apprend de ses trades")
    _add_data_args(run)
    run.add_argument("--db", default="patternbot.db")
    run.add_argument("--use-ai", action="store_true")
    run.add_argument("--improve-every", type=int, default=30, help="trades clôturés entre deux cycles")
    run.add_argument("--poll", type=float, default=60.0, help="secondes entre deux lectures (mode exchange)")
    live = sub.add_parser("run-live", help="trading RÉEL MT5 (FTMO) : triple verrou + garde-fou FTMO")
    live.add_argument("--config", required=True)
    live.add_argument("--db", default="patternbot.db")
    live.add_argument("--use-ai", action="store_true")
    live.add_argument("--improve-every", type=int, default=30)
    live.add_argument("--poll", type=float, default=60.0)
    appr = sub.add_parser("approve", help="approuver une version validée (réel)")
    appr.add_argument("version"); appr.add_argument("--db", default="patternbot.db")
    p = sub.add_parser("history"); p.add_argument("--db", default="patternbot.db")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "init-config":
            Path(args.path).parent.mkdir(parents=True, exist_ok=True)
            save_settings(Settings(), args.path)
            print(f"Config écrite : {args.path}")
            return 0
        if args.cmd == "history":
            store = ExperimentStore(args.db)
            for row in store.history():
                print(json.dumps(row, ensure_ascii=False))
            return 0

        if args.cmd == "approve":
            ExperimentStore(args.db).promote(args.version)
            print(f"{args.version} promue.")
            return 0

        settings = load_settings(args.config)
        setup_logging(settings.logging.level, settings.logging.file)
        if args.cmd == "run-live":
            ex = settings.execution
            orchestrator = None
            if args.use_ai:
                adapters = build_adapters(settings.ai)
                orchestrator = AIOrchestrator(adapters, settings) if adapters else None
            runner = PaperRunner(settings, ExperimentStore(args.db), orchestrator, args.improve_every)
            fetch = lambda: fetch_mt5(ex.mt5_symbol, ex.mt5_timeframe, 1000, ex.mt5_server_utc_offset_hours)
            runner.run_forever(fetch, args.poll)
            return 0

        df = _load_data(args, settings)

        if args.cmd == "scan":
            engine = SignalEngine(settings)
            for m in engine.scanner.scan(df):
                print(f"{m.name:26s} {m.direction:8s} score={m.score:.2f} confirmé={m.confirmed}")
            signal = engine.build_signal(df, engine.scanner.scan(df))
            print("Signal:", None if signal is None else f"{signal.direction} conf={signal.confidence:.2f}")
        elif args.cmd == "backtest":
            res = Backtester(settings).run(df)
            print(json.dumps(res.metrics, indent=2, default=str))
        elif args.cmd == "validate":
            report = Validator().validate(df, settings)
            print(json.dumps(report.to_dict(), indent=2, default=str))
            return 0 if report.passed else 2
        elif args.cmd == "run-paper":
            orchestrator = None
            if args.use_ai:
                adapters = build_adapters(settings.ai)
                orchestrator = AIOrchestrator(adapters, settings) if adapters else None
            runner = PaperRunner(settings, ExperimentStore(args.db), orchestrator, args.improve_every)
            if args.exchange:
                runner.run_forever(lambda: _load_data(args, settings), args.poll)
            else:
                runner.run_replay(df)
            print(f"Version active : {runner.version} | promotions : {runner.promotions} | "
                  f"equity paper : {runner.broker.equity():.2f}")
        elif args.cmd == "improve":
            orchestrator = None
            if args.use_ai:
                adapters = build_adapters(settings.ai)
                orchestrator = AIOrchestrator(adapters, settings) if adapters else None
                if orchestrator is None:
                    print("Aucune IA disponible : repli sur les règles.", file=sys.stderr)
            loop = ImprovementLoop(ExperimentStore(args.db), orchestrator=orchestrator)
            result = loop.run_cycle(df, settings)
            print(f"Base {result.base_version} -> promue: {result.promoted}")
            for o in result.outcomes:
                print(f"  [{o.status:8s}] {o.version} {o.hypothesis.description} {o.hypothesis.overrides}"
                      + ("" if o.status == "promoted" or o.status == "improved" else f" ({o.reason[:80]})"))
    except PatternBotError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
