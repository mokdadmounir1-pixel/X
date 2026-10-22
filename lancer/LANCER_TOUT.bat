@echo off
cd /d "%~dp0\.."
set FTMO_ALGO_ALLOWED_SERVER=MetaQuotes-Demo
echo === 1/3 Controle des donnees MT5 (lecture seule, aucun ordre) ===
python -m ftmo_algo data-check --mt5 --instruments EURUSD,GBPUSD,XAUUSD --start 2020-01-01 --out results_real
start "Recherche reelle" cmd /k python -m ftmo_algo research --mt5 --instruments EURUSD,GBPUSD,XAUUSD --start 2020-01-01 --workers 4 --out results_real --tag real1
start "Dashboard" cmd /k python -m ftmo_algo dashboard --mt5 --instruments EURUSD,GBPUSD,XAUUSD --start 2023-01-01 --replay-days 25 --out results_real --port 8790
echo.
echo Ouvre ensuite http://127.0.0.1:8790 dans ton navigateur.
echo Si un message dit "MetaTrader5" ou "initialize", ouvre MetaTrader 5 et reessaie.
pause
