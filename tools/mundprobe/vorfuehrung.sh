#!/bin/bash
# Leyla Vorfuehrung: startet avtr/vorfuehrung.py im Behaelter (Modelle, Grafikkarte, Port 8090).
# Schalter stehen, wenn gewuenscht, in avtr/vorfuehrung_schalter.txt (eine Zeile). Legt Claude vor dem Beenden
# avtr/vorfuehrung_neu.txt an, startet der Dienst mit den neuen Schaltern gleich wieder (kein neuer Doppelklick).
export AVTR1_LOCAL_STORAGE=/work/avtr/storage HF_HOME=/work/avtr/hf HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
cd /app
rm -f /work/avtr/vorfuehrung_neu.txt
while true; do
  ARGS=""
  [ -f /work/avtr/vorfuehrung_schalter.txt ] && ARGS=$(tr -d '\r\n' < /work/avtr/vorfuehrung_schalter.txt)
  pixi run -e renderer python /work/avtr/vorfuehrung.py $ARGS
  [ -f /work/avtr/vorfuehrung_neu.txt ] || break
  rm -f /work/avtr/vorfuehrung_neu.txt
done
