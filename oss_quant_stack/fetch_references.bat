@echo off
rem Clone en LECTURE le dépôt de référence KalshiMarketMaker (MIT) à côté du projet ; rien n'est exécuté ni installé.
cd /d "%~dp0"
if not exist references mkdir references
if not exist references\kalshimarketmaker git clone --depth 1 https://github.com/rodlaf/kalshimarketmaker references\kalshimarketmaker
pause
