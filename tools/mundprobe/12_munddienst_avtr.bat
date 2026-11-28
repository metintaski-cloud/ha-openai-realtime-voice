@echo off
setlocal
cd /d "%~dp0"
title Leyla Mund Dienst: Leyla spricht live am Fernseher
echo.
echo   Leyla Mund Dienst: dein PC rechnet Leylas Mund live und schickt das Bild an den Fernseher.
echo   Ports 8090 (Bild) und 8091 (Ton vom Add on), nur im Heimnetz.
echo   Der Start dauert etwa eine Minute. Dieses Fenster bitte offen lassen. Zum Beenden einfach schliessen.
echo.
docker version >nul 2>&1
if errorlevel 1 (
  echo   Docker laeuft nicht. Bitte Docker Desktop starten und diese Datei noch einmal doppelklicken.
  pause
  exit /b 1
)
ipconfig | findstr /c:"IPv4" > avtr\pc_adresse.txt
docker run --rm --gpus all -p 8090:8090 -p 8091:8091 -v "%cd%:/work" leyla-mund-avtr bash /work/avtr/munddienst.sh
echo.
echo   Mund Dienst beendet.
timeout /t 10
