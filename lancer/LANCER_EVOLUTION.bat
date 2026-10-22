@echo off
cd /d "%~dp0\.."
set FTMO_ALGO_ALLOWED_SERVER=MetaQuotes-Demo
REM A lancer APRES la fin de la recherche (fenetre "Recherche reelle" terminee).
REM Boucle d amelioration continue : relance toutes les 24 h, laisse cette fenetre ouverte.
python -m ftmo_algo evolve --mt5 --instruments EURUSD,GBPUSD,XAUUSD --start 2020-01-01 --workers 2 --out results_real --loop --every-hours 24 --resume
pause
