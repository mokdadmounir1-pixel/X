rem NOTE : mode HISTORIQUE (une fenetre par processus). Le plus simple est lancer_tout.bat : le terminal lance et relance tout seul la simulation.
@echo off
rem Lance l'automatisation 24 h/24 (une fenêtre par processus). Lecture seule côté MT5 ; le lanceur reste en OBSERVATION sans approbation signée.
cd /d "%~dp0\.."
set QUANTBOT_STATE=%CD%\runtime\live_state.db
rem (l'extraction MT5 est faite par la synchronisation automatique du terminal ; data_daemon.py reste utilisable seul, jamais en même temps)
start "quantbot - file de recherche" cmd /k python scripts\research_queue.py
start "quantbot - simulation PAPER (toutes les strategies)" cmd /k python scripts\paper_all.py --spec specs\inst_strategies_v1.json specs\smc_v1b.json specs\gold_quant_v1.json specs\apex_pullback_v1.json specs\stop_hunt_v2.json specs\stop_hunt_v3.json specs\mtf_confluence_v1.json specs\il_svr_v1.json
start "quantbot - simulation PAPER crypto (Coinbase, lecture seule)" cmd /k python scripts\paper_all.py --source coinbase
start "quantbot - terminal http://127.0.0.1:3214" cmd /k python -m quantbot ui --port 3214 --open --no-workers
