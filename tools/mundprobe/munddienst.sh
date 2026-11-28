#!/bin/bash
# Leyla Mund Dienst: startet avtr/munddienst.py im Behaelter (Modelle, Grafikkarte, Ports 8090 und 8091).
# Schalter stehen, wenn gewuenscht, in avtr/munddienst_schalter.txt (eine Zeile). Legt Claude vor dem Beenden
# avtr/munddienst_neu.txt an, startet der Dienst mit den neuen Schaltern gleich wieder (kein neuer Doppelklick).
export AVTR1_LOCAL_STORAGE=/work/avtr/storage HF_HOME=/work/avtr/hf HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
cd /app
rm -f /work/avtr/munddienst_neu.txt
while true; do
  ARGS=""
  [ -f /work/avtr/munddienst_schalter.txt ] && ARGS=$(tr -d '\r\n' < /work/avtr/munddienst_schalter.txt)
  pixi run -e renderer python /work/avtr/munddienst.py $ARGS
  [ -f /work/avtr/munddienst_neu.txt ] || break
  rm -f /work/avtr/munddienst_neu.txt
done
