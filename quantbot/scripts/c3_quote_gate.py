"""Précontrôle local de disponibilité pour C3 ; aucune API d'ordres."""
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5


def main(output):
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    report = dict(kind="PRECONTROLE_AVANT_C3",captured_at_utc=datetime.now(timezone.utc).isoformat(),
                  symbol="XAUUSD",samples=[],eligible_for_c3=False,orders_sent=0,order_checks=0,
                  conclusions=dict(timezone="NON_CONCLUANT",freshness="NON_CONCLUANT",current_bar="NON_CONCLUANT",live_spread="NON_CONCLUANT"))
    initialized = mt5.initialize(r"C:\Program Files\MetaTrader 5\terminal64.exe",timeout=15000)
    report["initialize"] = dict(ok=bool(initialized),last_error=mt5.last_error())
    try:
        if initialized:
            account=mt5.account_info();terminal=mt5.terminal_info()
            if account is None or terminal is None or not terminal.connected or account.trade_mode!=mt5.ACCOUNT_TRADE_MODE_DEMO:
                report["reason"]="Compte démo connecté non confirmé ; aucune autre identité essayée"
            else:
                identity=(account.login,account.server,account.trade_mode)
                report["terminal_build"]=terminal.build
                for i in range(5):
                    tick=mt5.symbol_info_tick("XAUUSD")
                    now=time.time()
                    report["samples"].append(dict(system_epoch=now,system_utc=datetime.fromtimestamp(now,timezone.utc).isoformat(),
                        tick_epoch_raw=int(tick.time) if tick else None,tick_msc_raw=int(tick.time_msc) if tick else None,
                        bid=float(tick.bid) if tick else None,ask=float(tick.ask) if tick else None))
                    if i<4:time.sleep(1)
                stamps=[s["tick_msc_raw"] for s in report["samples"] if s["tick_msc_raw"] is not None]
                progressed=sum(b>a for a,b in zip(stamps,stamps[1:]))
                regressed=any(b<a for a,b in zip(stamps,stamps[1:]))
                last=report["samples"][-1]
                delta=(last["tick_epoch_raw"]-last["system_epoch"]) if last["tick_epoch_raw"] else None
                candidate=round(delta/1800)/2 if delta is not None else None
                plausible=candidate is not None and abs(candidate)<=14 and abs(delta-candidate*3600)<=5
                prices_valid=all(s["bid"] is not None and math.isfinite(s["bid"]) and math.isfinite(s["ask"]) and 0<s["bid"]<=s["ask"] for s in report["samples"])
                final=mt5.account_info()
                stable=final is not None and (final.login,final.server,final.trade_mode)==identity
                report.update(progressive_updates=progressed,timestamp_regressed=regressed,identity_stable=stable,
                              eligible_for_c3=bool(progressed>=2 and not regressed and plausible and prices_valid and stable))
                report["reason"]=("Ticks progressifs et compatibles ; poursuivre les mesures C3, aucun fuseau encore certifié" if report["eligible_for_c3"] else
                                  "Cotations insuffisamment progressives ou non cohérentes ; C3 différée, aucune conclusion sur le fuseau, la fraîcheur, la bougie courante ou le spread en direct")
        else:
            report["reason"]="Initialisation impossible ; aucun autre terminal essayé"
    finally:
        if initialized:mt5.shutdown()
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"eligible_for_c3":report["eligible_for_c3"],"reason":report["reason"]},ensure_ascii=True))


if __name__=="__main__":main(sys.argv[1])
