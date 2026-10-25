"""Lanceur Windows MT5 : observation par défaut, approbation humaine inchangée.

--status ne charge pas MT5 et ouvre SQLite en lecture seule.
--kill crée le fichier d'arrêt. --clear-kill exige une saisie humaine exacte.
Les stratégies, le broker, les approbations et le coupe-circuit ne sont pas modifiés.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib
import json
import logging
import math
from pathlib import Path
import re
import sqlite3
import sys
import time

MAX_CONSECUTIVE_ERRORS = 5


class CleanStop(Exception):
    """Arrêt propre du lanceur SANS drapeau persistant (ex. erreurs de cycle transitoires répétées)."""


def safe_text(value, login=None):
    text = str(value)
    if login is not None:
        full = str(login)
        text = text.replace(full, "*" * max(2,len(full)-2) + full[-2:])
    # Le mode hors connexion ne doit pas exiger de lire un identifiant de compte.
    return re.sub(r"(?i)(compte\s*[=:]?\s*)(\d{3,})",
                  lambda m:m[1] + "*" * (len(m[2])-2) + m[2][-2:], text)


def emit(value, login=None):
    # Une ligne JSON par événement : fichier de recette exploitable en JSONL.
    print(safe_text(json.dumps(value,ensure_ascii=False,allow_nan=False),login),flush=True)


def local_path(root, value):
    p = Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (root/p).resolve()


def arguments(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project",default=str(Path(__file__).resolve().parents[1]),help="Racine contenant quantbot/live")
    p.add_argument("--symbol",default="XAUUSD")
    p.add_argument("--strategy",default="vwap")
    p.add_argument("--spec",default="specs/inst_strategies_v1.json")
    p.add_argument("--approvals",default="approved_strategies.json")
    p.add_argument("--state",default="runtime/live_state.db")
    p.add_argument("--kill-file",default=None,help="Par défaut : KILL à côté de la base d'état")
    p.add_argument("--poll",type=float,default=5.0)
    p.add_argument("--servers",nargs="+",default=["MetaQuotes-Demo"],help="Liste blanche exacte, sans identifiants")
    p.add_argument("--terminal",default=r"C:\Program Files\MetaTrader 5\terminal64.exe")
    p.add_argument("--max-steps",type=int,help="Recette bornée ; absent = boucle jusqu'à Ctrl+C")
    action = p.add_mutually_exclusive_group()
    action.add_argument("--status",action="store_true")
    action.add_argument("--kill",action="store_true")
    action.add_argument("--clear-kill",action="store_true")
    action.add_argument("--resolve-intent",metavar="ID",help="Résolution HUMAINE d'une intention PENDING/SENT/UNKNOWN après vérification dans le terminal")
    p.add_argument("--outcome",choices=["NOT_EXECUTED","EXECUTED"],help="Avec --resolve-intent : ce que le terminal montre réellement")
    p.add_argument("--ticket",type=int,help="Avec --outcome EXECUTED : ticket de la position constatée dans le terminal")
    args = p.parse_args(argv)
    if not math.isfinite(args.poll) or not .1<=args.poll<=3600:
        p.error("--poll doit être fini, entre 0,1 et 3600 secondes")
    if args.max_steps is not None and args.max_steps<1:
        p.error("--max-steps doit être positif")
    args.root = Path(args.project).expanduser().resolve()
    args.spec_path = local_path(args.root,args.spec)
    args.approvals_path = local_path(args.root,args.approvals)
    args.state_path = local_path(args.root,args.state)
    args.kill_path = local_path(args.root,args.kill_file) if args.kill_file else args.state_path.parent/"KILL"
    targets=[args.state_path,args.kill_path,args.spec_path,args.approvals_path]
    if len(set(targets))!=len(targets):
        p.error("État, KILL, spec et approbations doivent être des fichiers distincts")
    if args.state_path.with_name(args.state_path.name+".runner.lock") in (args.kill_path,args.spec_path,args.approvals_path):
        p.error("Le fichier de verrou ne peut pas être utilisé comme KILL, spec ou approbations")
    if args.resolve_intent and not args.outcome:
        p.error("--resolve-intent exige --outcome NOT_EXECUTED|EXECUTED")
    if args.outcome and not args.resolve_intent:
        p.error("--outcome n'a de sens qu'avec --resolve-intent")
    if args.outcome == "EXECUTED" and not args.ticket:
        p.error("--outcome EXECUTED exige --ticket (position constatée dans le terminal)")
    if args.ticket and args.outcome != "EXECUTED":
        p.error("--ticket n'est valable qu'avec --outcome EXECUTED")
    return args


def read_status(state_path, kill_path):
    """Ne pas créer une base inexistante, ni modifier une base existante."""
    result=dict(state=str(state_path),kill_file=str(kill_path),exists=state_path.is_file(),
                mode="NON_DEMARRE",reason="Aucune base d'état",kill_reasons=[],unresolved_intents=[],running=None)
    if kill_path.exists():
        result["kill_reasons"].append("fichier KILL présent")
    if not state_path.is_file():
        return result
    conn = sqlite3.connect(state_path.resolve().as_uri()+"?mode=ro",uri=True,timeout=3)
    conn.row_factory=sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        kv={r["key"]:json.loads(r["value"]) for r in conn.execute("SELECT key,value FROM kv")}
        intents=[dict(r) for r in conn.execute("SELECT id,kind,status,strategy,created,updated FROM intents WHERE status IN ('PENDING','SENT','UNKNOWN') ORDER BY created")]
        if kv.get("kill"):
            result["kill_reasons"].append(safe_text("déclenché : "+str(kv["kill"])))
        if intents:
            result["kill_reasons"].append(str(len(intents))+" intention(s) non rapprochée(s) ; aucun rejeu autorisé par le lanceur")
        heartbeat=kv.get("heartbeat")
        age=time.time()-heartbeat if isinstance(heartbeat,(int,float)) and math.isfinite(heartbeat) else None
        result.update(mode=kv.get("mode","NON_DEMARRE"),reason=safe_text(kv.get("why",kv.get("launcher_stop_reason","Raison absente"))),
                      last_bar=kv.get("last_bar"),heartbeat_age_seconds=age,
                      unresolved_intents=intents,running=kv.get("launcher_running"),
                      stopped_at=kv.get("launcher_stopped_at"),stop_reason=kv.get("launcher_stop_reason"))
        return result
    finally:
        conn.close()


@contextmanager
def state_lock(path):
    """Un seul lanceur par base. Le verrou OS est relâché même après crash."""
    path.parent.mkdir(parents=True,exist_ok=True)
    handle=path.with_name(path.name+".runner.lock").open("a+b")
    locked=False
    try:
        if handle.seek(0,2)==0:
            handle.write(b"0");handle.flush()
        handle.seek(0)
        try:
            if sys.platform=="win32":
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
        except OSError:
            raise RuntimeError("Cette base est déjà utilisée par un autre lanceur") from None
        yield
    finally:
        if locked:
            handle.seek(0)
            if sys.platform=="win32":
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        handle.close()


def load_project(root):
    required=[root/"quantbot/live/runner.py",root/"quantbot/live/state.py",root/"quantbot/live/killswitch.py"]
    if not all(p.is_file() for p in required):
        raise ValueError("Racine quantbot invalide : utiliser --project avec le dossier contenant quantbot/live")
    # Empêcher un package homonyme préchargé depuis un autre dépôt.
    prior=sys.modules.get("quantbot")
    if prior is not None and Path(prior.__file__).resolve().parent != root/"quantbot":
        raise ValueError("Un autre package quantbot est déjà chargé : relancer dans un nouveau processus")
    sys.path.insert(0,str(root))
    from quantbot.live.state import StateStore
    from quantbot.live.killswitch import KillSwitch
    return StateStore,KillSwitch


def clear_kill(args):
    status=read_status(args.state_path,args.kill_path)
    if status["unresolved_intents"]:
        raise PermissionError("Levée refusée : intentions PENDING/SENT/UNKNOWN à rapprocher d'abord")
    if not sys.stdin.isatty():
        raise PermissionError("Saisie humaine interactive requise ; aucune confirmation par argument ou tube")
    print("Lever les drapeaux d'arrêt ne valide aucune stratégie. Taper exactement JE_COMPRENDS :",flush=True)
    if input().strip()!="JE_COMPRENDS":
        raise PermissionError("Confirmation incorrecte : arrêt conservé")
    with state_lock(args.state_path):
        # Revérifier après la saisie, sous le verrou du lanceur.
        if read_status(args.state_path,args.kill_path)["unresolved_intents"]:
            raise PermissionError("État modifié : intentions non rapprochées, arrêt conservé")
        if args.state_path.is_file():
            StateStore,KillSwitch=load_project(args.root)
            store=StateStore(args.state_path)
            try:
                if store.open_intents():
                    raise PermissionError("Intentions non rapprochées, arrêt conservé")
                KillSwitch(store,args.kill_path).clear("JE_COMPRENDS")
            finally:
                store.close()
        # Suppression du fichier par action humaine explicite, pas par le bot.
        args.kill_path.unlink(missing_ok=True)
    emit(dict(action="CLEAR_KILL",reason="Levée humaine explicite ; approbations inchangées",status=read_status(args.state_path,args.kill_path)))
    return 0


def resolve_intent(args):
    """Clôt à la main une intention non rapprochée. Ne touche NI au drapeau d'arrêt NI au fichier KILL NI aux approbations."""
    if not args.state_path.is_file():
        raise ValueError("Aucune base d'état : rien à résoudre")
    if not sys.stdin.isatty():
        raise PermissionError("Saisie humaine interactive requise ; aucune confirmation par argument ou tube")
    with state_lock(args.state_path):
        StateStore,_KillSwitch=load_project(args.root)
        store=StateStore(args.state_path)
        try:
            intent=store.intent(args.resolve_intent)
            if intent is None:
                raise ValueError("Intention introuvable")
            if intent["status"] not in ("PENDING","SENT","UNKNOWN"):
                raise PermissionError("Intention déjà résolue ou jamais envoyée : statut "+str(intent["status"]))
            emit(dict(action="RESOLVE_INTENT_APERCU",intent={k:intent[k] for k in ("id","kind","side","status","detail","ticket","strategy")},
                      outcome=args.outcome,ticket=args.ticket))
            print("Vérifiez DANS le terminal (positions ET historique des ordres/deals) que cette intention "
                  +("n'a produit AUCUNE position ni deal" if args.outcome=="NOT_EXECUTED" else "correspond à la position "+str(args.ticket))
                  +". Cette commande ne lève pas le coupe-circuit. Taper exactement JE_VERIFIE_LE_TERMINAL :",flush=True)
            if input().strip()!="JE_VERIFIE_LE_TERMINAL":
                raise PermissionError("Confirmation incorrecte : intention conservée")
            store.mark(intent["id"],"RESOLVED_"+args.outcome,"résolu par un humain après vérification dans le terminal",args.ticket)
            store.log("WARNING","intent_resolved_by_human",intent["id"]+" -> "+args.outcome)
        finally:
            store.close()
    emit(dict(action="RESOLVE_INTENT",intent=args.resolve_intent,outcome=args.outcome,status=read_status(args.state_path,args.kill_path)))
    return 0


class MaskLogins(logging.Filter):
    def __init__(self,login):
        super().__init__();self.login=login
    def filter(self,record):
        record.msg=safe_text(record.getMessage(),self.login);record.args=()
        return True


def account_guard(mt5, servers, expected=None):
    acct=mt5.account_info();terminal=mt5.terminal_info()
    if acct is None or terminal is None or not terminal.connected:
        raise RuntimeError("Compte ou terminal déconnecté")
    if acct.trade_mode!=mt5.ACCOUNT_TRADE_MODE_DEMO:
        raise PermissionError("Compte non démo : le lanceur refuse toute exécution, même en observation")
    if acct.server not in servers:
        raise PermissionError("Serveur observé hors liste blanche")
    identity=(acct.login,acct.server,acct.trade_mode)
    if expected is not None and identity!=expected:
        raise PermissionError("Identité du compte modifiée : arrêt du lanceur")
    return identity


def run(args):
    StateStore,KillSwitch=load_project(args.root)
    # Vérifier la spec avant de toucher au terminal.
    if not args.spec_path.is_file():
        raise ValueError("Spec introuvable")
    spec=json.loads(args.spec_path.read_text(encoding="utf-8-sig"))
    strategy=spec.get("strategies",{}).get(args.strategy)
    if not isinstance(strategy,dict) or args.symbol not in strategy.get("instruments",[]):
        raise ValueError("Stratégie/instrument absents de la spec")
    from quantbot.live.runner import LiveRunner
    from quantbot.logging_utils import setup_logging
    # Seul le module MT5 réel est chargé par le lanceur d'exploitation.
    mt5=importlib.import_module("MetaTrader5")
    runner=None;initialized=False;login=None;reason="initialisation interrompue"
    with state_lock(args.state_path):
        try:
            # Inconnu, pending ou sent ne sont jamais rejoués par ce lanceur.
            status=read_status(args.state_path,args.kill_path)
            if status["unresolved_intents"]:
                raise PermissionError("Reprise refusée : intentions PENDING/SENT/UNKNOWN non rapprochées ; utiliser --status")
            initialized=bool(mt5.initialize(str(Path(args.terminal)),timeout=15000))
            if not initialized:
                raise RuntimeError("initialize() a échoué : "+str(mt5.last_error()))
            identity=account_guard(mt5,tuple(args.servers));login=identity[0]
            logger=setup_logging("INFO")
            for handler in logger.handlers:
                handler.addFilter(MaskLogins(login))
            runner=LiveRunner(mt5,symbol=args.symbol,strategy_id=args.strategy,spec_path=args.spec_path,
                approvals_path=args.approvals_path,state_path=args.state_path,kill_file=args.kill_path,
                allowed_servers=tuple(args.servers))
            mode=runner.setup()
            account_guard(mt5,tuple(args.servers),identity)
            runner.state.set("launcher_running",True)
            runner.state.set("launcher_started_at",time.time())
            emit(dict(mode=mode,reason=runner.state.get("why"),symbol=args.symbol,strategy=args.strategy,
                      statistics="PAPER sur prix MT5 réels ; exécutions et PnL simulés" if mode=="OBSERVATION" else "ORDRES DEMO sous contrôles du broker",
                      project=str(args.root),state=str(args.state_path)),login)
            reason="limite de recette atteinte"
            consecutive_errors=0
            while args.max_steps is None or runner.steps<args.max_steps:
                account_guard(mt5,tuple(args.servers),identity)
                result=runner.step()
                if result=="crash":
                    # exception inattendue : LiveRunner a déjà posé le coupe-circuit persistant
                    reason="exception inattendue dans un cycle ; arrêt conservateur du lanceur"
                    runner.kill.trigger(reason)
                    raise RuntimeError(reason+" ; consulter --status et les événements")
                if result=="error":
                    # erreur ordinaire (ex. lecture de barres momentanément impossible) : journalisée par le runner,
                    # le lanceur continue ; trop d'erreurs d'affilée = arrêt propre SANS drapeau persistant.
                    consecutive_errors+=1
                    emit(dict(event="ERREUR_CYCLE",consecutive=consecutive_errors,max=MAX_CONSECUTIVE_ERRORS),login)
                    if consecutive_errors>=MAX_CONSECUTIVE_ERRORS:
                        raise CleanStop(str(consecutive_errors)+" erreurs de cycle consécutives ; arrêt propre, aucun drapeau persistant posé")
                else:
                    consecutive_errors=0
                if args.max_steps is None or runner.steps<args.max_steps:
                    time.sleep(args.poll)
            return 0
        except KeyboardInterrupt:
            reason="Ctrl+C demandé par l'utilisateur"
            return 130
        except CleanStop as exc:
            reason=safe_text(str(exc),login)
            return 1
        except BaseException as exc:
            # Inclut SystemExit d'une spec/coûts invalides ; aucune boucle muette.
            reason=safe_text(type(exc).__name__+": "+str(exc),login)
            if runner is not None:
                runner.kill.trigger("lanceur interrompu : "+reason)
            raise
        finally:
            try:
                if runner is not None:
                    try:
                        runner.state.set("launcher_running",False)
                        runner.state.set("launcher_stopped_at",time.time())
                        runner.state.set("launcher_stop_reason",reason)
                        runner.state.log("INFO","launcher_stop",reason)
                    finally:
                        runner.state.close()
            finally:
                if initialized:
                    mt5.shutdown()
            if runner is not None:
                emit(dict(event="ARRET",reason=reason,orders_forced_closed=False),login)


def main(argv=None):
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,"reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args=arguments(argv)
    try:
        if args.status:
            emit(read_status(args.state_path,args.kill_path));return 0
        if args.kill:
            args.kill_path.parent.mkdir(parents=True,exist_ok=True)
            # Ne pas réécrire un fichier KILL déjà présent.
            try:
                with args.kill_path.open("x",encoding="utf-8") as f:
                    f.write("Arrêt demandé explicitement par l'utilisateur\n")
            except FileExistsError:
                pass
            emit(dict(action="KILL",path=str(args.kill_path),reason="Fichier d'arrêt présent ; aucune clôture forcée"));return 0
        if args.clear_kill:
            return clear_kill(args)
        if args.resolve_intent:
            return resolve_intent(args)
        return run(args)
    except KeyboardInterrupt:
        emit(dict(event="ARRET",reason="Ctrl+C"));return 130
    except (Exception,SystemExit) as exc:
        emit(dict(mode="ARRETE",reason=safe_text(type(exc).__name__+": "+str(exc)),
                  next_step="Consulter --status ; aucun état inconnu n'est rejoué et aucune approbation n'est créée"))
        return 1


if __name__=="__main__":
    raise SystemExit(main())
