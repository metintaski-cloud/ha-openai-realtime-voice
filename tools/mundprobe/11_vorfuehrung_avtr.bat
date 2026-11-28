@echo off
setlocal
cd /d "%~dp0"
title Leyla Mund 6: Vorfuehrung, Leyla spricht live
echo.
echo   Leyla Vorfuehrung: dein PC rechnet Leylas Mund live und schickt Bild und Ton ins Heimnetz (Port 8090).
echo   Der Start dauert etwa eine Minute. Dieses Fenster bitte offen lassen. Zum Beenden einfach schliessen.
echo.
docker version >nul 2>&1
if errorlevel 1 (
  echo   Docker laeuft nicht. Bitte Docker Desktop starten und diese Datei noch einmal doppelklicken.
  pause
  exit /b 1
)
ipconfig | findstr /c:"IPv4" > avtr\pc_adresse.txt
docker run --rm --gpus all -p 8090:8090 -v "%cd%:/work" leyla-mund-avtr bash /work/avtr/vorfuehrung.sh
echo.
echo   Vorfuehrung beendet.
timeout /t 10
