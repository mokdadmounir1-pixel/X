import argparse
import json


def main():
    ap = argparse.ArgumentParser(prog="quantlab")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("research", help="walk-forward + null test + cost stress on every strategy")
    r.add_argument("--csv"); r.add_argument("--ccxt", metavar="SYMBOL"); r.add_argument("--bars", type=int, default=30000)
    r.add_argument("--splits", type=int, default=4); r.add_argument("--iters", type=int, default=30); r.add_argument("--null", type=int, default=20)
    r.add_argument("--only", nargs="*")
    d = sub.add_parser("dashboard", help="live paper-trading dashboard")
    d.add_argument("--port", type=int, default=8767); d.add_argument("--speed", type=float, default=2.0)
    d.add_argument("--csv"); d.add_argument("--ccxt", metavar="SYMBOL")
    i = sub.add_parser("install", help="install + smoke-test the open-source toolbox")
    i.add_argument("--pip-only", action="store_true"); i.add_argument("--git-only", action="store_true")
    a = ap.parse_args()

    if a.cmd == "install":
        from .tools.install import install_all
        for x in install_all(only_pip=a.pip_only, only_git=a.git_only):
            print(f"{x['status']:7s} {x['id']:22s} {x['detail'][:70]}")
        return
    from .sources import load
    df, src = load(csv=a.csv, symbol=a.ccxt, bars=getattr(a, "bars", 30000))
    if a.cmd == "research":
        from .research import run_all
        out = run_all(df, a.only, source=src, splits=a.splits, n_iter=a.iters, null_n=a.null)
        print(f"data: {src}, {len(df)} bars")
        for x in out["reports"]:
            o = x["oos"]
            print(f"{x['verdict']:5s} {x['gates_passed']}/7 {x['strategy']:17s} oos_trades={o['trades']:4d} exp={o['expectancy_r']:+.3f}R pf={o['profit_factor']:.2f} null_p={x['null']['p_value']:.2f}")
    else:
        from .live import LiveSession
        from .strategies import REGISTRY
        from .dashboard.server import serve
        import pathlib
        params = {}
        res = pathlib.Path(__file__).resolve().parents[1] / "results" / "latest.json"
        if res.exists():
            params = {r["strategy"]: r["params"] for r in json.loads(res.read_text())["reports"]}
        names = [n for n in REGISTRY if n != "ml_direction"]
        serve(LiveSession(df, names, params_by=params, speed=a.speed, source="replay" if src.startswith("synthetic") else "history"), port=a.port)


main()
