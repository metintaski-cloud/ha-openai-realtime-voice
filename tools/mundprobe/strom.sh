#!/bin/bash
# Leyla Strom Test: startet den kleinen Test Dienst (avtr/strom.py) im Behaelter. Kein Modell, keine Grafikkarte.
cd /app
exec pixi run -e renderer python /work/avtr/strom.py
