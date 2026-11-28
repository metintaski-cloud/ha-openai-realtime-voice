@echo off
setlocal
cd /d "%~dp0"
title Leyla Mund 5: Test Uebertragung zum Fernseher
echo.
echo   Leyla Test Uebertragung: dein PC schickt ein fertiges Leyla Video als laufenden Strom ins Heimnetz (Port 8090).
echo   Dieses Fenster bitte offen lassen. Zum Beenden einfach schliessen.
echo.
docker version >/dev/null 2>&1
if errorlevel 1 (
  echo   Docker laeuft nicht. Bitte Docker Desktop starten und diese Datei noch einmal doppelklicken.
  pause
  exit /b 1
)
ipconfig | findstr /c:"IPv4" > avtr\pc_adresse.txt
docker run --rm -p 8090:8090 -v "%cd%:/work" leyla-mund-avtr bash /work/avtr/strom.sh
echo.
echo   Test Uebertragung beendet.
timeout /t 10
