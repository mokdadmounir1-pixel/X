@echo off
rem Lance l'automatisation 24 h/24 (une fenêtre par processus). Lecture seule côté MT5 ; le lanceur reste en OBSERVATION sans approbation signée.
cd /d "%~dp0\.."
set QUANTBOT_STATE=%CD%\runtime\live_state.db
start "quantbot - extraction MT5" cmd /k python scripts\data_daemon.py --symbols XAUUSD EURUSD USTEC --timeframes M15 H1 --interval 30
start "quantbot - file de recherche" cmd /k python scripts\research_queue.py
start "quantbot - lanceur (OBSERVATION)" cmd /k python scripts\run_live.py --project . --symbol XAUUSD --strategy vwap --state runtime\live_state.db
start "quantbot - interface" cmd /k python -m quantbot ui
