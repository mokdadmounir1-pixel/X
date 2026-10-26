@echo off
rem TOUT lancer en UN double-clic : pre-vol (connexion MT5 verifiee en clair) puis simulation PAPER de toutes les strategies sur les prix reels + interface.
rem Aucun ordre n'est envoye a MetaTrader 5. La fenetre doit rester ouverte.
title quantbot - tout lancer
cd /d "%~dp0"
echo ================================================
echo   QUANTBOT - connexion MT5 + trades SIMULES
echo ================================================
where python >nul 2>nul
if errorlevel 1 (
  echo [ERREUR] Python est introuvable. Installez Python 3.10+ depuis python.org en cochant "Add python.exe to PATH", puis relancez.
  pause
  exit /b 1
)
python -c "import fastapi, uvicorn, pandas, MetaTrader5" >nul 2>nul
if errorlevel 1 (
  echo Premier lancement : installation des dependances, patientez...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERREUR] L'installation a echoue. Lisez le message ci-dessus.
    pause
    exit /b 1
  )
)
echo.
echo --- PRE-VOL (ce qui est connecte, ce qui bloque, quoi faire) ---
python scripts\preflight.py
if errorlevel 1 (
  echo.
  echo Corrigez les points [BLOQUANT] ci-dessus puis relancez ce fichier.
  pause
  exit /b 1
)
if not exist config\broker_profile.json (
  echo.
  echo --- PREMIER LANCEMENT : profil de TON courtier (noms des symboles, contrat, spread reel sur 20 s) ---
  python scripts\broker_profile.py --seconds 20
)
echo.
echo Demarrage des fenetres : simulation PAPER (MT5 + crypto) et interface http://127.0.0.1:3214/
call scripts\start_all.bat
echo.
echo Tout est lance. Laissez les fenetres ouvertes. Controle de performance : python scripts\audit_performance.py
pause
