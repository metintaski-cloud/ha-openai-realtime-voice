@echo off
setlocal
cd /d "%~dp0"
title Leyla Mund 4 (AVTR-1): Werkstatt
echo.
echo   Leyla Werkstatt: Claude rechnet hier die Proben "Mund auf dem bewegten Clip".
echo   Dieses Fenster bitte offen lassen. Zum Beenden einfach schliessen.
echo.
docker version >nul 2>&1
if errorlevel 1 (
  echo   Docker laeuft nicht. Bitte Docker Desktop starten und diese Datei noch einmal doppelklicken.
  pause
  exit /b 1
)
docker run --rm --gpus all -v "%cd%:/work" leyla-mund-avtr bash /work/avtr/werkstatt.sh
echo.
echo   Werkstatt beendet.
timeout /t 10
