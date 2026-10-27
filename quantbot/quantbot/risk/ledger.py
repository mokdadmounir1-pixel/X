"""Registre de portefeuille FTMO SIMULÉ : toutes les stratégies en simulation PAPER sont comptées comme si elles tradaient UN SEUL compte de 100 000 $ (chacune avec son propre risque par trade).

Règles modélisées (à vérifier sur ftmo.com, elles peuvent changer) : perte journalière 5 % (jour calé sur Europe/Prague), perte totale 10 %, tampons internes 4 % / 8 % : au tampon, plus aucune entrée ;
à la limite dure, le compte simulé est « perdu ». Le coupe-circuit écrit le fichier KILL que chaque simulation lit : plus aucune nouvelle entrée. Il n'est JAMAIS levé automatiquement (levée humaine).
Aucun ordre réel : il ne s'agit que de comptabiliser des trades simulés.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

import pandas as pd

CAPITAL = 100_000.0
TZ = "Europe/Prague"


def evaluate(rows: list[dict], now: Optional[float] = None, capital: float = CAPITAL, daily_limit: float = 0.05, total_limit: float = 0.10, daily_buffer: float = 0.04, total_buffer: float = 0.08) -> dict:
    now = time.time() if now is None else now
    day0 = pd.Timestamp(now, unit="s", tz="UTC").tz_convert(TZ).normalize().tz_convert("UTC").timestamp() * 1000.0
    closed = [r for r in rows if not r.get("open") and r.get("pnl") is not None]; opened = [r for r in rows if r.get("open") and r.get("pnl") is not None]
    realised = sum(r["pnl"] for r in closed); latent = sum(r["pnl"] for r in opened)
    today = sum(r["pnl"] for r in closed if r["recorded_ms"] >= day0) + latent                         # le latent compte entièrement dans le jour (prudent)
    by: dict = {}
    for r in closed + opened:
        a = by.setdefault(r["strategy_code"], {"strategy_code": r["strategy_code"], "pnl": 0.0, "n": 0, "wins": 0}); a["pnl"] += r["pnl"]
        if not r.get("open"):
            a["n"] += 1; a["wins"] += int(r["pnl"] > 0)
    for a in by.values():
        a["win_rate"] = a["wins"] / a["n"] if a["n"] else None
    daily_pct, total_pct = today / capital, (realised + latent) / capital
    reasons = []
    if daily_pct <= -daily_buffer: reasons.append(f"perte journalière {daily_pct:.2%} <= -{daily_buffer:.0%} (tampon)")
    if total_pct <= -total_buffer: reasons.append(f"perte totale {total_pct:.2%} <= -{total_buffer:.0%} (tampon)")
    breached = daily_pct <= -daily_limit or total_pct <= -total_limit
    return {"capital": capital, "equity": capital + realised + latent, "pnl_realised": realised, "pnl_latent": latent, "pnl_today": today, "daily_pct": daily_pct, "total_pct": total_pct,
            "limits": {"daily": daily_limit, "total": total_limit, "daily_buffer": daily_buffer, "total_buffer": total_buffer}, "halt_new": bool(reasons) or breached, "breached": breached,
            "reasons": reasons + (["LIMITE DURE FTMO atteinte : compte simulé perdu"] if breached else []), "n_closed": len(closed), "n_open": len(opened),
            "by_strategy": sorted(by.values(), key=lambda a: -a["pnl"]), "note": "Comptabilité de trades SIMULÉS sur un compte unique de 100 000 $ ; règles FTMO à vérifier."}


def enforce(root: Path, status: dict, now: Optional[float] = None) -> bool:
    """Écrit le fichier KILL lu par toutes les simulations si le registre demande l'arrêt. Retourne True si le fichier a été (ou était déjà) posé. Ne le retire jamais."""
    kill = Path(root) / "runtime" / "paper" / "KILL"
    if status["halt_new"]:
        kill.parent.mkdir(parents=True, exist_ok=True)
        if not kill.exists():
            kill.write_text(json.dumps({"ts": time.time() if now is None else now, "reasons": status["reasons"], "by": "portfolio_ledger", "note": "levée humaine uniquement : supprimer ce fichier après analyse"}, ensure_ascii=False, indent=1), encoding="utf-8")
        return True
    return kill.exists()


def prometheus(status: dict, by_extra: Optional[dict] = None) -> str:
    """Exposition texte (format Prometheus) du registre : lecture seule, aucune valeur inventée."""
    lines = ["# TYPE quantbot_equity gauge", f"quantbot_equity {status['equity']:.2f}", "# TYPE quantbot_daily_pnl_pct gauge", f"quantbot_daily_pnl_pct {status['daily_pct']:.6f}",
             "# TYPE quantbot_total_pnl_pct gauge", f"quantbot_total_pnl_pct {status['total_pct']:.6f}", "# TYPE quantbot_halt_new gauge", f"quantbot_halt_new {int(status['halt_new'])}",
             "# TYPE quantbot_strategy_pnl gauge"]
    for a in status["by_strategy"]:
        lines.append(f'quantbot_strategy_pnl{{strategy="{a["strategy_code"]}"}} {a["pnl"]:.2f}')
        lines.append(f'quantbot_strategy_trades{{strategy="{a["strategy_code"]}"}} {a["n"]}')
        if a["win_rate"] is not None:
            lines.append(f'quantbot_strategy_win_rate{{strategy="{a["strategy_code"]}"}} {a["win_rate"]:.4f}')
    return "\n".join(lines) + "\n"


class LedgerMonitor:
    """Thread : évalue le registre toutes les `interval` s, écrit runtime/ledger.json et pose KILL au besoin."""

    def __init__(self, root: Path, interval: float = 30.0) -> None:
        self.root, self.interval, self._stop = Path(root), interval, threading.Event()

    def tick(self) -> dict:
        from ..gui.book import build_book
        st = evaluate(build_book(self.root, "all")["rows"]); st["kill_file"] = enforce(self.root, st)
        try:
            (self.root / "runtime").mkdir(parents=True, exist_ok=True); (self.root / "runtime" / "ledger.json").write_text(json.dumps(st, indent=1, default=str), encoding="utf-8")
        except OSError:
            pass
        return st

    def start(self) -> threading.Thread:
        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception:
                    pass
                self._stop.wait(self.interval)
        t = threading.Thread(target=loop, daemon=True, name="quantbot-ledger"); t.start(); return t

    def stop(self) -> None:
        self._stop.set()
