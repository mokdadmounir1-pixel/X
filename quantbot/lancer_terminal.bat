@echo off
rem Lance le terminal quantbot (lecture seule) et ouvre le navigateur. Double-cliquez ici. La fenetre doit rester ouverte tant que vous utilisez le terminal.
title quantbot - terminal
cd /d "%~dp0"
echo ================================================
echo   QUANTBOT - terminal (lecture seule)
echo ================================================
where python >nul 2>nul
if errorlevel 1 (
  echo [ERREUR] Python est introuvable.
  echo Installez Python 3.10 ou plus recent depuis python.org et COCHEZ "Add python.exe to PATH", puis relancez.
  pause
  exit /b 1
)
python -c "import fastapi, uvicorn, pandas" >nul 2>nul
if errorlevel 1 (
  echo Premier lancement : installation des dependances, patientez quelques minutes...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERREUR] L'installation a echoue. Lisez le message ci-dessus.
    pause
    exit /b 1
  )
)
echo Demarrage... le navigateur va s'ouvrir tout seul. Pour arreter : fermez cette fenetre.
echo.
python -m quantbot ui --open
echo.
echo Le terminal s'est arrete. Le message juste au-dessus donne la cause.
pause
