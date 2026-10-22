@echo off
cd /d "%~dp0\.."
set FTMO_ALGO_ALLOWED_SERVER=MetaQuotes-Demo
echo ATTENTION : ceci passe de VRAIS ORDRES sur ton compte DEMO MetaQuotes-Demo.
echo Risque 0.25 pour cent par trade, gardien des regles FTMO actif. Aucun avantage n est valide.
set /p OK=Tape OUI pour lancer le trading DEMO : 
if /i not "%OK%"=="OUI" exit /b
python -m ftmo_algo demo --mt5 --instruments EURUSD,GBPUSD,XAUUSD --risk 0.25 --out results_real --minutes 600
pause
