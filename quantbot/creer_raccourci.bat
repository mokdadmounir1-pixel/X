@echo off
rem Double-cliquez ICI une seule fois : place "Quantbot - Terminal" sur le Bureau (fichier de lancement + raccourci avec l'icone si possible).
setlocal
set "ROOT=%~dp0"
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')" 2^>nul`) do set "DESK=%%D"
if not defined DESK set "DESK=%USERPROFILE%\Desktop"
echo Bureau detecte : %DESK%
> "%DESK%\Quantbot - Terminal.bat" (
  echo @echo off
  echo call "%ROOT%lancer_terminal.bat"
)
if exist "%DESK%\Quantbot - Terminal.bat" (echo [OK] Fichier "Quantbot - Terminal.bat" cree sur le Bureau.) else (echo [ERREUR] Impossible d'ecrire sur le Bureau.)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%DESK%\Quantbot - Terminal.lnk'); $s.TargetPath='%ROOT%lancer_terminal.bat'; $s.WorkingDirectory='%ROOT%'; if (Test-Path '%ROOT%assets\fennec_diamond.ico') { $s.IconLocation='%ROOT%assets\fennec_diamond.ico' }; $s.Save()" 2>nul
if exist "%DESK%\Quantbot - Terminal.lnk" (echo [OK] Raccourci avec icone cree : "Quantbot - Terminal.lnk" ) else (echo [info] Raccourci avec icone non cree : utilisez "Quantbot - Terminal.bat".)
echo.
echo Termine. Double-cliquez sur "Quantbot - Terminal" sur le Bureau.
pause
