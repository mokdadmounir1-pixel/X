"""Pré-vol : vérifie en clair, point par point, que quantbot est CONNECTÉ à MetaTrader 5 et prêt à prendre des trades SIMULÉS sur les prix réels.

    python scripts/preflight.py [--terminal "C:\\Program Files\\MetaTrader 5\\terminal64.exe"] [--symbol XAUUSD]

Chaque ligne : [OK] / [ATTENTION] / [BLOQUANT] + QUOI FAIRE. Lecture seule : aucun ordre, aucun secret affiché (login masqué à 2 chiffres).
Code de sortie 0 = aucun point bloquant. Ce script ne passe JAMAIS d'ordre et n'active pas le mode DEMO_ACTIF (décision humaine écrite, voir docs/EXPLOITATION.md).
"""
import argparse, importlib, json, socket, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))

OK, WARN, BLOCK = "OK", "ATTENTION", "BLOQUANT"


def mask(login) -> str:
    s = str(login); return s[:2] + "*" * max(len(s) - 2, 0)


def run(root: Path = ROOT, terminal: str | None = None, symbol: str = "XAUUSD", mt5=None, port: int = 3214, importer=importlib.import_module, now=time.time) -> list[dict]:
    out: list[dict] = []
    def add(level, what, fix=""): out.append({"level": level, "what": what, "fix": fix})

    for mod in ("numpy", "pandas", "fastapi", "uvicorn"):
        try: importer(mod)
        except ImportError: add(BLOCK, f"module Python « {mod} » absent", "lancer lancer_terminal.bat (il installe tout) ou : pip install -r requirements.txt")
    if mt5 is None:
        try: mt5 = importer("MetaTrader5")
        except ImportError:
            add(BLOCK, "module MetaTrader5 absent", "Windows uniquement : pip install MetaTrader5 (lancer_terminal.bat le fait). Sur Linux/Mac MT5 n'est pas joignable."); mt5 = None
    if mt5 is not None:
        ok = mt5.initialize(terminal, timeout=15000) if terminal else mt5.initialize()
        if not ok:
            add(BLOCK, f"MT5 injoignable : {mt5.last_error()}", "ouvrir MetaTrader 5, se connecter au compte DÉMO, laisser la fenêtre ouverte, puis relancer ; sinon passer --terminal avec le chemin de terminal64.exe")
        else:
            try:
                term, acct = mt5.terminal_info(), mt5.account_info()
                if term is not None and not getattr(term, "connected", True): add(BLOCK, "MT5 ouvert mais NON connecté au serveur du courtier", "vérifier la connexion internet et le compte (barre d'état en bas à droite de MT5)")
                elif acct is None: add(BLOCK, "aucun compte connecté dans MT5", "Fichier > Se connecter au compte de trading")
                else:
                    demo = acct.trade_mode == getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
                    add(OK if demo else BLOCK, f"compte {mask(acct.login)} @ {acct.server} : {'DÉMO' if demo else 'NON DÉMO'}", "" if demo else "quantbot refuse tout compte non démo : se connecter à un compte démo")
                    if term is not None and not getattr(term, "trade_allowed", True): add(WARN, "le trading automatique est désactivé dans MT5", "bouton « Algo Trading » (inutile pour la simulation et la lecture)")
                if not mt5.symbol_select(symbol, True): add(BLOCK, f"symbole {symbol} introuvable chez ce courtier", "Vue > Symboles : chercher l'or (XAUUSD, GOLD, XAUUSD.a...) et le lui donner via --symbol")
                else:
                    info, tick = mt5.symbol_info(symbol), mt5.symbol_info_tick(symbol)
                    if getattr(info, "trade_mode", 4) == 0: add(WARN, f"{symbol} : trade_mode = 0 (désactivé chez ce courtier)", "les données arrivent mais aucun ordre ne serait accepté ; sans effet sur la simulation PAPER")
                    if tick is None: add(BLOCK, f"aucune cotation reçue pour {symbol}", "afficher le symbole dans la Surveillance du marché de MT5")
                    else:
                        age = now() - getattr(tick, "time", now()); sp = tick.ask - tick.bid
                        add(OK if age < 300 else WARN, f"cotation {symbol} : bid {tick.bid} ask {tick.ask} (spread {sp:.2f}), âge {age:.0f} s", "" if age < 300 else "cotation figée : marché fermé (week-end / pause) ou flux coupé ; la simulation reprendra à la réouverture")
            finally:
                mt5.shutdown()
    live = root / "data" / "live"
    try:
        live.mkdir(parents=True, exist_ok=True); t = live / ".w"; t.write_text("x"); t.unlink(); add(OK, "dossier data/live inscriptible")
    except OSError as e: add(BLOCK, f"data/live non inscriptible : {e}", "vérifier les droits du dossier (ne pas installer sous Program Files)")
    try:
        from quantbot.filelock import exclusive_lock
        with exclusive_lock(live / "daemon.lock"): add(OK, "aucun autre programme n'écrit dans data/live")
    except RuntimeError: add(WARN, "un autre programme écrit déjà dans data/live (data_daemon ?)", "un seul écrivain à la fois : fermer l'autre fenêtre (la synchronisation du terminal le remplace)")
    except Exception: pass
    with socket.socket() as s:
        s.settimeout(0.5); busy = s.connect_ex(("127.0.0.1", port)) == 0
    add(OK if not busy else WARN, f"port {port} {'libre' if not busy else 'déjà utilisé'}", "" if not busy else "le terminal est peut-être déjà lancé : ouvrir http://127.0.0.1:%d/ ; sinon quantbot prendra un autre port" % port)
    n_specs = len(list((root / "specs").glob("*.json"))) if (root / "specs").exists() else 0
    add(OK if n_specs else BLOCK, f"{n_specs} specs préenregistrées", "" if n_specs else "dépôt incomplet : refaire git pull")
    real = list((root / "data" / "real").glob("*_M15.csv")) if (root / "data" / "real").exists() else []
    add(OK if real else WARN, f"{len(real)} export(s) de recherche dans data/real", "" if real else "pas bloquant : les backtests utiliseront les barres synchronisées de data/live après quelques heures de collecte")
    try:
        from quantbot.clock import clock_health, clock_offset
        c = clock_offset(timeout=2.0); h = clock_health(c)
        add(OK if h == "ok" else WARN, "horloge : " + (f"décalage {c['offset_s']*1000:+.0f} ms ({c['server']})" if c.get("status") == "ok" else "serveur de temps injoignable"), "" if h == "ok" else "Paramètres Windows > Heure > Synchroniser maintenant")
    except Exception: pass
    return out


def main(argv=None, **kw) -> int:
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("--terminal"); ap.add_argument("--symbol", default="XAUUSD"); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--json")
    a = ap.parse_args(argv); res = run(Path(a.root), a.terminal, a.symbol, **kw)
    for r in res:
        print(f"[{r['level']:9s}] {r['what']}" + (f"\n             -> {r['fix']}" if r["fix"] else ""))
    blockers = [r for r in res if r["level"] == BLOCK]
    print("\nRÉSULTAT :", "PRÊT : quantbot peut prendre des trades SIMULÉS sur les prix réels." if not blockers else f"{len(blockers)} point(s) BLOQUANT(s) à corriger ci-dessus.")
    print("Aucun ordre n'est envoyé à MetaTrader 5 : le mode DEMO_ACTIF exige ton autorisation écrite et l'approbation signée (docs/EXPLOITATION.md).")
    if a.json: Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if blockers else 0


if __name__ == "__main__":
    sys.exit(main())
