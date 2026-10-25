@echo off
rem Compile le terminal quantbot en application Windows (dossier dist\quantbot-terminal\quantbot-terminal.exe).
rem Prérequis : Python 3.10+ (64 bits). Icône : assets\fennec_diamond.ico (déposez la vôtre pour remplacer l'icône générée).
setlocal
cd /d "%~dp0"
if not exist .venv-build ( python -m venv .venv-build || goto :err )
call .venv-build\Scripts\activate || goto :err
python -m pip install --upgrade pip || goto :err
pip install -r requirements.txt -r requirements-gui.txt pyinstaller || goto :err
python tools\make_icon.py || goto :err
pyinstaller --noconfirm --clean build\quantbot_terminal.spec || goto :err
rem Données de l'utilisateur à côté de l'exécutable : specs (préenregistrées), reports (historique) ; data\real, data\live et runtime\ sont à y copier / y générer.
robocopy specs dist\quantbot-terminal\specs /E /NFL /NDL /NJH /NJS >nul
robocopy reports dist\quantbot-terminal\reports /E /NFL /NDL /NJH /NJS /XF *.log >nul
if not exist dist\quantbot-terminal\data\real mkdir dist\quantbot-terminal\data\real
copy /Y data\real\PROVENANCE.json dist\quantbot-terminal\data\real\ >nul
echo.
echo OK : dist\quantbot-terminal\quantbot-terminal.exe
echo Copiez vos CSV dans dist\quantbot-terminal\data\real (python scripts\setup_data.py depuis le projet les retrouve par empreinte).
exit /b 0
:err
echo ECHEC de la compilation.
exit /b 1
