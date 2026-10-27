"""Profil du courtier, en LECTURE SEULE : nom des symboles chez ce courtier, spécifications de contrat, spread réellement observé, coûts de départ pour les specs.

    python scripts/broker_profile.py [--terminal "C:\\...\\terminal64.exe"] [--symbols XAUUSD EURUSD USTEC] [--seconds 120] [--commission-per-lot-side 3.5]

Écrit config/broker_profile.json : symbol_map (nom canonique -> nom du courtier), comptes (login masqué), spécifications, spread échantillonné (1 Hz), coûts recommandés.
La commission n'est pas exposée par l'API de symbole : donne-la avec --commission-per-lot-side (valeur du site du courtier) ; sinon elle est marquée « non connue » et JAMAIS supposée nulle.
Aucun ordre n'est envoyé. Un compte non démo est refusé.
"""
import argparse, json, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.live.symbols import resolve

FIELDS = ["digits", "point", "trade_contract_size", "trade_tick_size", "trade_tick_value", "volume_min", "volume_step", "volume_max", "swap_long", "swap_short", "swap_mode",
          "trade_mode", "trade_exemode", "filling_mode", "trade_stops_level", "trade_freeze_level", "currency_profit", "currency_margin"]


def mask(login) -> str:
    s = str(login); return s[:2] + "*" * max(len(s) - 2, 0)


def build(mt5, symbols, seconds: float, commission: float | None, sleep=time.sleep, now=time.time) -> dict:
    acct = mt5.account_info(); term = mt5.terminal_info() if hasattr(mt5, "terminal_info") else None
    if acct is None:
        raise SystemExit("Aucun compte connecté dans MT5.")
    if acct.trade_mode != getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0):
        raise SystemExit("Compte NON démo : profil refusé (quantbot ne lit que le démo).")
    prof = {"generated_utc": now(), "account": {"login": mask(acct.login), "server": acct.server, "currency": acct.currency, "leverage": getattr(acct, "leverage", None),
                                                  "company": getattr(acct, "company", None) or getattr(term, "company", None)}, "symbol_map": {}, "symbols": {}, "unresolved": {}, "costs": {}}
    for canon in symbols:
        r = resolve(mt5, canon)
        if r["broker"] is None:
            prof["unresolved"][canon] = r.get("similar", []); continue
        prof["symbol_map"][canon] = r["broker"]; mt5.symbol_select(r["broker"], True); info = mt5.symbol_info(r["broker"])
        prof["symbols"][canon] = {"broker_name": r["broker"], "match": r["status"], **{f: getattr(info, f, None) for f in FIELDS}}
        sp, n = [], max(int(seconds), 1)
        for _ in range(n):
            t = mt5.symbol_info_tick(r["broker"])
            if t is not None and t.ask > t.bid: sp.append((t.ask - t.bid, (t.ask + t.bid) / 2))
            sleep(1.0)
        if sp:
            ab = [s for s, _ in sp]; mid = statistics.median(p for _, p in sp); med = statistics.median(ab)
            q = lambda p: sorted(ab)[min(int(p * len(ab)), len(ab) - 1)]
            prof["symbols"][canon]["spread_observed"] = {"n": len(ab), "p10": q(0.10), "median": med, "p90": q(0.90), "mid_price": mid}
            cost = {"spread_frac": med / mid if mid else None, "basis": f"spread médian observé sur {len(ab)} échantillons"}
            size = prof["symbols"][canon].get("trade_contract_size")
            if commission is not None and size and mid:
                cost["fee_rate"] = commission / (mid * size); cost["fee_basis"] = f"commission {commission} {acct.currency}/lot/côté sur contrat {size}"
            else:
                cost["fee_rate"] = None; cost["fee_basis"] = "commission NON CONNUE (ne pas supposer 0) : relever sur le site du courtier et relancer avec --commission-per-lot-side"
            prof["costs"][canon] = cost
        else:
            prof["symbols"][canon]["spread_observed"] = None
    return prof


def main(argv=None, mt5=None, sleep=time.sleep) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("--terminal"); ap.add_argument("--symbols", nargs="+", default=["XAUUSD", "EURUSD", "USTEC"])
    ap.add_argument("--seconds", type=float, default=120.0); ap.add_argument("--commission-per-lot-side", type=float); ap.add_argument("--root", default=str(ROOT)); a = ap.parse_args(argv)
    if mt5 is None:
        import MetaTrader5 as mt5  # type: ignore
    from quantbot.live.terminal import mt5_initialize
    if not mt5_initialize(mt5, a.terminal):
        print(f"MT5 injoignable : {mt5.last_error()} -> ouvre MetaTrader 5 et connecte-toi au compte démo."); return 1
    try:
        prof = build(mt5, a.symbols, a.seconds, a.commission_per_lot_side, sleep=sleep)
    finally:
        mt5.shutdown()
    out = Path(a.root) / "config" / "broker_profile.json"; out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(prof, indent=1, default=str), encoding="utf-8")
    print(f"Courtier : {prof['account']['server']} (compte {prof['account']['login']}, {prof['account']['currency']}, levier {prof['account']['leverage']})")
    for c, b in prof["symbol_map"].items():
        s = prof["symbols"][c]; so = s.get("spread_observed"); cost = prof["costs"].get(c, {})
        print(f"  {c} -> {b} [{s['match']}] | contrat {s['trade_contract_size']} | lot min {s['volume_min']} | spread médian " + (f"{so['median']:.4f}" if so else "non observé (marché fermé ?)") + f" | {cost.get('fee_basis', '')}")
    for c, sim in prof["unresolved"].items():
        print(f"  {c} : INTROUVABLE chez ce courtier. Symboles proches : {sim or 'aucun'} -> relance avec le bon nom via config/broker_profile.json (symbol_map).")
    print(f"Profil écrit : {out}"); return 0


if __name__ == "__main__":
    sys.exit(main())
