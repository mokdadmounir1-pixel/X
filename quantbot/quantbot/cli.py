"""Interface en ligne de commande : python -m quantbot <commande>.

Les anciennes commandes d'amélioration/exécution sont retirées jusqu'aux phases 5-6 du plan
(boucle en ombre, exécution démo durcie) : aucune exécution d'ordres n'est exposée ici.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .backtest.engine import Backtester
from .config import Settings, load_settings, save_settings
from .data.loaders import fetch_ccxt, load_csv
from .data.mt5 import find_holes, load_mt5_csv, weekly_open_check
from .exceptions import ConfigError, PatternBotError
from .logging_utils import setup_logging
from .memory.store import ExperimentStore
from .signals.engine import SignalEngine


def _load_data(args):
    if args.mt5_csv:
        return load_mt5_csv(args.mt5_csv)
    if args.csv:
        return load_csv(args.csv, repair=True)
    if args.exchange:
        return fetch_ccxt(args.exchange, args.symbol or "BTC/USDT")
    raise ConfigError("Aucune source de données : --mt5-csv, --csv ou --exchange est obligatoire (aucune donnée de remplacement n'est générée)")


def _add_data_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config")
    p.add_argument("--mt5-csv", help="export MT5 (colonne time_broker_epoch)")
    p.add_argument("--csv")
    p.add_argument("--exchange", help="id ccxt, ex: binance")
    p.add_argument("--symbol")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser("quantbot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init-config")
    p.add_argument("path", nargs="?", default="config/default.json")
    for name in ("scan", "backtest", "audit-data"):
        _add_data_args(sub.add_parser(name))
    p = sub.add_parser("history")
    p.add_argument("--db", default="quantbot.db")
    ui = sub.add_parser("ui", help="terminal local (127.0.0.1, lecture seule) : trades, attribution, marché, backtests, risque")
    ui.add_argument("--port", type=int, default=8790)
    appr = sub.add_parser("approve", help="approuver une version validée")
    appr.add_argument("version")
    appr.add_argument("--db", default="quantbot.db")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "init-config":
            Path(args.path).parent.mkdir(parents=True, exist_ok=True)
            save_settings(Settings(), args.path)
            print(f"Config écrite : {args.path}")
            return 0
        if args.cmd == "history":
            for row in ExperimentStore(args.db).history():
                print(json.dumps(row, ensure_ascii=False))
            return 0
        if args.cmd == "ui":
            from .gui.server import serve
            serve(args.port)
            return 0
        if args.cmd == "approve":
            ExperimentStore(args.db).promote(args.version)
            print(f"{args.version} promue.")
            return 0

        settings = load_settings(args.config)
        setup_logging(settings.logging.level, settings.logging.file)
        df = _load_data(args)
        if args.cmd == "audit-data":
            print(json.dumps({"rows": len(df), "start": str(df.index[0]), "end": str(df.index[-1]),
                              "weekly_open": weekly_open_check(df),
                              "holes": find_holes(df, settings.backtest.max_gap_hours)}, indent=1))
        elif args.cmd == "scan":
            engine = SignalEngine(settings)
            matches = engine.scanner.scan(df)
            for m in matches:
                print(f"{m.name:26s} {m.direction:8s} score={m.score:.2f} confirmé={m.confirmed}")
            signal = engine.build_signal(df, matches)
            print("Signal:", None if signal is None else f"{signal.direction} conf={signal.confidence:.2f}")
        elif args.cmd == "backtest":
            print(json.dumps(Backtester(settings).run(df).metrics, indent=2, default=str))
    except PatternBotError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
