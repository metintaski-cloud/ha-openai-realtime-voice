#!/bin/bash
# Leyla Werkstatt: der Behaelter bleibt offen und rechnet eine Probe, sobald Claude die Datei avtr/los.txt
# in den Ordner legt (darin stehen nur die Schalter fuer avtr/probe.py). So muss fuer jeden Versuch
# kein neues Fenster gestartet werden. Beenden: das Fenster schliessen oder die Datei avtr/ende.txt anlegen.
export AVTR1_LOCAL_STORAGE=/work/avtr/storage HF_HOME=/work/avtr/hf HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
cd /app
rm -f /work/avtr/ende.txt
echo "bereit $(date '+%H:%M:%S')" > /work/avtr/werkstatt_status.txt
echo "Werkstatt bereit. Dieses Fenster offen lassen, solange Claude an der Probe arbeitet."
while true; do
  if [ -f /work/avtr/los.txt ]; then
    ARGS=$(tr -d '\r\n' < /work/avtr/los.txt)
    rm -f /work/avtr/los.txt
    echo "laeuft seit $(date '+%H:%M:%S'): $ARGS" > /work/avtr/werkstatt_status.txt
    echo "Probe laeuft: $ARGS"
    pixi run -e renderer python /work/avtr/probe.py $ARGS > /work/avtr/log_probe.txt 2>&1
    echo "fertig Code $? um $(date '+%H:%M:%S'): $ARGS" > /work/avtr/werkstatt_status.txt
    echo "Probe fertig."
  fi
  if [ -f /work/avtr/ende.txt ]; then
    rm -f /work/avtr/ende.txt
    echo "beendet $(date '+%H:%M:%S')" > /work/avtr/werkstatt_status.txt
    exit 0
  fi
  sleep 2
done
