"""Audit de performance à partir des journaux RÉELS du terminal (trades PAPER, journal d'exécution, ticks). Lecture seule.

    python scripts/audit_performance.py            # tableau lisible
    python scripts/audit_performance.py --json out.json
"""
import argparse, json, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.audit import execution_stats, gatekeeper, tick_inventory, trade_metrics
from quantbot.gui.book import build_book


def executions(root: Path) -> list[dict]:
    rows = []
    for db in list((root / "runtime").glob("*.db")) + list((root / "runtime" / "paper").glob("*.db")):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True); cur = con.execute("SELECT * FROM executions"); cols = [c[0] for c in cur.description]
            rows += [dict(zip(cols, r)) for r in cur.fetchall()]; con.close()
        except sqlite3.Error:
            continue
    return rows


def main(argv=None) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--json"); args = ap.parse_args(argv); root = Path(args.root)
    book = build_book(root, "all"); closed = [r for r in book["rows"] if not r["open"] and r["r"] is not None]
    ex = execution_stats(executions(root)); out = {"overall": {}, "by_strategy": {}, "execution": ex, "ticks": tick_inventory(root)}
    groups = {"TOUT": closed}
    for r in closed:
        groups.setdefault(r["strategy_code"], []).append(r)
    for name, rows in groups.items():
        m = trade_metrics([x["r"] for x in rows]); dd = book["metrics"]["drawdown_pct"] if name == "TOUT" else None
        out["overall" if name == "TOUT" else "by_strategy"][name] = {"metrics": m, "gate": gatekeeper(m, dd_frac=dd, latency_ms=ex.get("latency_ms")) if name == "TOUT" else gatekeeper(m, latency_ms=ex.get("latency_ms"))}
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    m = out["overall"].get("TOUT", {}).get("metrics", {"n": 0})
    print(f"Trades PAPER clos : {m['n']}")
    if m["n"]:
        print(f"  espérance {m['expectancy_r']:+.3f} R | PF {m['profit_factor']:.2f} | réussite {m['win_rate']:.1%} (seuil {m['breakeven_wr'] or float('nan'):.1%}) | DD {m['max_drawdown_r']:.1f} R | p {m['sign_flip_p']}")
        for c in out["overall"]["TOUT"]["gate"]:
            print(f"  [{c['state']:10s}] {c['check']} : {c['detail']}")
    print("Exécutions MT5 :", ex if ex else "aucune (aucun ordre envoyé)"); print("Ticks :", out["ticks"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
